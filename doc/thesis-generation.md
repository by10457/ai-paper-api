# 论文生成流程

本文说明从用户提交论文请求到生成 Word 文档的完整流程。

## 两种业务入口

### 直连接口

适合 `/home/by/wxy/edu-sys-server` 等业务系统直接调用。

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

## 结构化大纲协议

大纲在生成、前端编辑和正文任务提交阶段统一使用三级嵌套结构：

```json
[
  {
    "chapter": "绪论",
    "sections": [
      {
        "name": "研究背景",
        "abstract": "说明二级小节的写作要点。",
        "subsections": [
          {
            "name": "行业背景",
            "abstract": "说明三级小节的写作要点。"
          }
        ]
      }
    ]
  }
]
```

- 不再传 `three_level`：AI 根据目标篇幅和内容复杂度判断，默认两级，必要时局部细化三级；允许混合层级。`subsections` 为空代表无需细分，编辑器仍支持修改三级结构。
- 为兼容旧客户端，请求省略 `subsections` 时按空数组处理。
- 用户确认后的 `subsections` 会转换为 Markdown `###` 标题并进入正文生成；调用链不得在转发或保存大纲时丢弃该字段。

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

如果用户选择“不标注”，主流程会跳过参考文献生成。启用参考文献时，系统只接收具有可核验来源且通过业务主题相关性校验的结果，技术词重合仅用于辅助排序。目标总数和中英文比例均为尽力目标，不是生成失败条件；不足时不使用弱相关或不可核验文献凑数。

检索总预算为 180 秒，单供应商批次最多 60 秒；主检索后最多访问两个备用源，中英文各最多两轮补检，无新增有效文献即停止该语言的重复补检，必要时再以可用语言补总量。预算包括相关性审核；耗尽后保留已经验证的结果。HTTP/超时故障允许降级，内部程序错误和任务取消仍向上传递。

总量或英文不足时，以实际文献继续正文、引用及 DOCX 生成，记录非阻断质量提示。完全没有可用文献时，返回空列表，正文提示词改为待核实的研究方向/检索计划，不声称已有文献支持；清理单编号、合并编号及模型擅自附加的书目，文末显式显示“待补充参考文献”。已退款订单不会自动重新生成或扣费。

## 正文生成

入口：`services/thesis/content/fulltext_service.py`

输入：

- 用户确认的大纲 Markdown。
- 目标字数。
- 参考文献列表。
- 是否包含代码相关内容。

正文模型用途为 `fulltext`，如果未配置，会回退到 `default`。

为避免长文本单次输出达到供应商 token 上限后丢失后半章节，正文按用户确认大纲的一级章节分批生成：

- `target_word_count` 直接作为最终可见正文目标，不再使用固定的 `1.7` 折算系数；生成后会按相同口径进行收敛，默认验收区间为目标值的 90%-110%。
- 每次最多生成 3 个连续一级章节，7 章大纲会按 `3 + 3 + 1` 生成，避免每个批次重复使用全文目标。
- 模型返回 `length`、`max_tokens`、`max_output_tokens`，或批次缺少任一一级标题时，当前批次退化为逐章重生成。
- 逐章重生成后仍缺章或被截断时，任务按普通生成失败进入既有重试/最终退款流程，不生成残缺 Word 文件。
- 订单大纲在 API 边界校验章节和小节结构；章节、小节标题为空或章节没有小节时直接拒绝请求。

模型调用日志记录供应商返回的输入/输出 token 和 `finish_reason`，用于区分输出上限截断与普通模型漏写。部分 OpenAI 兼容供应商不返回这些字段，此时日志仍只记录输入、输出字符数。

任务完成状态同时记录两种正文长度：

- `fulltext_char_count`：模型 Markdown 原文长度，包含 Markdown 标记和图表占位 JSON，主要用于排查模型响应。
- `fulltext_word_count`：剔除图表占位和代码围栏后，按中文逐字、连续英文/数字逐词估算的可见正文长度，更接近 Word/WPS 的字数口径。

`truncation_warning` 使用 `fulltext_word_count` 与用户目标比较；低于目标的 90% 或高于 110% 时提示偏离目标。它是质量告警，不等同于模型达到 token 上限；是否被截断仍以模型 `finish_reason` 和章节完整性校验为准。

正文完成后还会执行交付质量整理：

- 用户没有提供真实项目材料或测试结果时，实施细节、运行环境、性能数据、测试结论和结论性表述会标记为“建议/待确认/待执行”，不得作为实测事实输出。
- 图表只有在存在用户提供或可核验的数据时才保留；未提供数据时不会生成虚构的性能趋势图。
- 最终引用按首次出现顺序重新编号，删除未引用文献，并校验每个文内编号都有对应文献。
- 未填写的封面、声明和致谢个人资料统一显示为 `【待补充：字段】`，并在任务结果中返回缺失字段。

任务状态的 `result_data` 返回实际生效配置和质量信息：

- `word_count`：目标、90%-110% 区间和实际可见正文字数。
- `reference_count`、`reference_language_counts`、`reference_sources`：最终可核验文献及语言构成。
- `reference_quality`：`status` 为 `complete`、`limited`、`unavailable` 或 `disabled`，并提供 `target_count`、`actual_count`、`target_languages`、`actual_languages`、`warnings`。
- `quality_warnings`：文献不足等非阻断提示，代码为 `reference_count_shortfall`、`reference_language_shortfall` 或 `references_unavailable`；不能按此字段将已完成任务视为失败。
- `citation_integrity`：文内引用与最终参考文献是否闭环。
  有文献为 `closed`；启用检索但零结果为 `no_references`；主动不标注为 `not_applicable`。最终覆盖率以实际文献列表为准，不按期望数量校验。
- `missing_profile_fields`：调用方仍需补齐的个人资料字段。
- `generated_suggestion_fields`：由模型提出但未经用户材料确认的建议内容类别。
- `effective_config`：最终采用的目标字数、文献数、外文开关和引用开关。

正文中可能包含两类结构：

- Markdown 表格：后续由 Word 文档层转换成三线表。
- 图片占位符：后续由图片层渲染成 PNG 并插入 Word。

Word 目录仍来自最终正文标题，但会兼容 `#1 标题`、`##1.1 标题` 等井号后缺少空格的常见模型输出，并忽略 Markdown 代码围栏内的 `#` 注释；生成进入文档阶段前已经完成大纲章节守恒校验。

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

允许 AI 生图时，Mermaid 渲染失败可转为 AI 插图兜底；关闭 AI 生图时只保留本地 Mermaid/图表渲染，失败项不会触发付费图片模型。

## Word 文档组装

入口：`services/thesis/document/docx_builder.py`

职责：

- 封面和基本信息。
- 中英文摘要、关键词。
- 目录、页码、章节样式。
- 目录缓存页码会同时估算正文、参考文献和致谢；参考文献跨页时，致谢页码随实际内容长度顺延。
- 正文段落。
- Markdown 表格转 Word 表格。
- 图片插入和图题。
- 参考文献、致谢。

文档构建通过：

```python
asyncio.to_thread(build_word_document, ...)
```

放到线程中执行，避免阻塞 FastAPI 事件循环。

### WSL 中的 DOCX 像素级检查

本地 WSL Ubuntu 使用 `/usr/bin/soffice` 将 DOCX 转换为 PDF，再使用
`/usr/bin/pdftoppm` 将 PDF 的每一页渲染为 PNG 逐页检查。开发环境需要安装：

```bash
sudo apt-get install libreoffice-writer poppler-utils fonts-noto-cjk
/usr/bin/soffice --version
/usr/bin/pdftoppm -v
```

结构测试只能验证 DOCX 的 OOXML 语义；修改分节、页码、目录、页眉页脚、字体或图表布局后，
还需要用上述 WSL 工具完成实际渲染检查。摘要和目录必须使用新页分节，避免 LibreOffice
忽略连续分节上的罗马页码重启设置。

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
