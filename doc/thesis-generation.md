# 论文生成流程

本文说明从用户提交论文请求到生成 Word 文档的完整流程。

## 两种业务入口

### 直连接口

适合 `/home/by/wxy/wxy-server` 等业务系统直接调用。

流程：

1. 调用 `POST /api/v1/thesis/outline` 生成大纲。
2. 调用 `POST /api/v1/thesis/generate` 提交生成任务。
3. 系统扣减积分，创建 `paper_orders` 和 `paper_generation_tasks`。
4. 任务进入 Redis 队列。
5. worker 生成论文。
6. 查询 `GET /api/v1/thesis/status/{task_id}` 或等待回调。
7. 下载 `GET /api/v1/thesis/download/{task_id}` 或使用回调中的下载链接。

### 订单接口

适合 Web 用户使用。

流程：

1. `POST /api/v1/thesis/outlines` 生成并保存大纲记录。
2. 用户编辑确认大纲。
3. `POST /api/v1/thesis/orders` 创建待支付论文订单。
4. `POST /api/v1/thesis/orders/pay` 扣积分并创建生成任务。
5. 任务进入 Redis 队列。
6. worker 生成论文。
7. 前端通过 `orders/status` 或 `orders/events` 获取进度。
8. 完成后通过 `orders/download-url` 获取下载链接。

## 积分和幂等

扣费发生在：

- 直连接口：`POST /api/v1/thesis/generate`
- 订单接口：`POST /api/v1/thesis/orders/pay`

创建订单不扣费，支付后扣费。

建议调用方传入：

```http
Idempotency-Key: <业务系统订单号或稳定唯一值>
```

作用：

- 避免 HTTP 重试重复扣积分。
- 避免重复创建论文生成任务。
- 便于从业务系统订单号反查生成任务。

## Redis 队列

论文生成不在 HTTP 请求线程中执行，而是进入 Redis 队列：

| Redis key | 类型 | 作用 |
| --- | --- | --- |
| `ai-paper:queue:paper:ready` | list | 可立即执行的任务。 |
| `ai-paper:queue:paper:delayed` | zset | 延迟重试任务。 |
| `ai-paper:queue:paper:enqueued` | set | 入队去重集合。 |

worker 每隔 `PAPER_WORKER_POLL_SECONDS` 秒取任务，最多同时执行：

```env
PAPER_GENERATION_CONCURRENCY=20
```

## 生成主流程顺序

主流程在 `services/thesis/generation/pipeline.py`。

整体顺序：

1. 发布 `started` 进度。
2. 参考文献检索和格式化。
3. 论文正文生成。
4. 摘要、关键词、致谢并发生成。
5. 从正文解析图片占位符。
6. Mermaid、图表、AI 插图并发渲染。
7. Word 文档组装。
8. 文档保存到本地并上传远端存储。
9. 回写订单和任务状态。
10. 回调业务系统。

## 参考文献

入口：`services/thesis/content/reference_service.py`

模式：

```env
REFERENCE_PROVIDER_MODE=wfapi
```

| 模式 | 说明 |
| --- | --- |
| `wfapi` | 中英文都用万方开放平台。 |
| `serpapi` | 中英文都用 SerpAPI Google Scholar。 |
| `mixed` | 中文万方，英文 SerpAPI。 |

如果用户选择“不标注”，主流程会跳过参考文献生成。

## 正文生成

入口：`services/thesis/content/fulltext_service.py`

输入：

- 用户确认的大纲 Markdown。
- 目标字数。
- 参考文献列表。
- 是否包含代码相关内容。

正文模型用途为 `fulltext`，如果未配置，会回退到 `default`。

正文中可能包含两类结构：

- Markdown 表格：后续由 Word 文档层转换成三线表。
- 图片占位符：后续由图片层渲染成 PNG 并插入 Word。

## 摘要、关键词和致谢

入口：`services/thesis/content/abstract_service.py`

摘要和致谢属于锦上添花流程，主流程使用 best-effort 包装：

- 成功：写入 Word。
- 失败：使用空字符串，不阻断整篇论文生成。

## 图片和图表

入口：`services/thesis/image/renderer.py`

支持：

| 类型 | 来源 | 说明 |
| --- | --- | --- |
| Mermaid | 本地 `mmdc` + Chromium | 适合流程图、架构图、时序图等。 |
| chart | 本地 matplotlib | 适合柱状图、折线图、饼图。 |
| ai_image | 第三方图片模型 API | 适合概念插图和 Mermaid 失败兜底。 |
| fallback | 跳过渲染 | 占位符解析失败或无法渲染。 |

并发配置：

```env
MERMAID_RENDER_CONCURRENCY=2
CHART_RENDER_CONCURRENCY=6
AI_IMAGE_RENDER_CONCURRENCY=6
IMAGE_MODEL_CONCURRENCY=6
```

Mermaid 渲染失败时，会自动转 AI 插图兜底，避免 Word 中完全没有图。

## Word 文档组装

入口：`services/thesis/document/docx_builder.py`

职责：

- 封面和基本信息。
- 中英文摘要、关键词。
- 目录、页码、章节样式。
- 正文段落。
- Markdown 表格转 Word 表格。
- 图片插入和图题。
- 参考文献、致谢。

文档构建通过：

```python
asyncio.to_thread(build_word_document, ...)
```

放到线程中执行，避免阻塞 FastAPI 事件循环。

## 存储和回调

生成出的 `.docx` 先保存在：

```text
public/output/thesis/{task_id}/{title}-{task_id}.docx
```

然后调用 `store_document(...)`：

1. 记录本地兜底文件。
2. 按 `STORAGE_PROVIDER` 上传远端。
3. 生成下载链接。
4. 写入任务状态和订单。
5. 调用 `notify_callback(...)` 回调业务系统。

## 失败、重试和退费

模型供应商额度不足或认证配置错误：

- 任务直接失败。
- 回写用户可见错误。
- 退回已扣积分。

普通生成失败：

- 按 `PAPER_GENERATION_MAX_RETRIES` 自动延迟重试。
- 重试延迟由 `PAPER_GENERATION_RETRY_DELAY_SECONDS` 控制。
- 达到最大重试次数后退积分并标记失败。

远端对象存储失败：

- 不会让论文任务失败。
- 降级返回本地文件下载链接。

回调失败：

- 不会让论文任务失败。
- 最多重试 3 次。
- 最终失败会记录日志。

## 状态阶段

常见进度阶段：

| stage | 含义 |
| --- | --- |
| `queued` | 已进入队列。 |
| `started` | worker 已开始处理。 |
| `references` | 检索和整理参考文献。 |
| `fulltext` | 生成正文。 |
| `abstracts` | 生成摘要、关键词和致谢。 |
| `figures` | 渲染图表和插图。 |
| `document` | 组装 Word 文档。 |
| `storage` | 保存和上传论文文件。 |
| `completed` | 生成完成。 |
| `failed` | 生成失败。 |

前端可通过 SSE 接口持续接收这些状态。
