# 接口对接

本文说明业务系统、Web 前端和管理后台如何对接 AI Paper API。

## 个人信息与文档占位

大纲、完整论文及三类材料请求均不接收姓名、学号、班级、学院、专业、指导教师、学位类别和个人年月等封面信息，也不接收 `student_profile`。提交未声明字段会返回 422；大纲接口不再接受任意 `form_params` 字典，请使用顶层 `target_word_count` 等明确字段。不提供旧字段兼容转换。

文档封面与声明页保留 `【待补充：…】` 占位，用户下载后离线填写；`missing_profile_fields` 是文档待填写项提示，不是要求通过接口提交的信息。完整论文致谢直接输出离线填写提示，不再调用模型生成个人经历；DOCX 作者元数据使用通用产品名。请勿在题目或补充说明等自由文本中填写个人信息。

## 认证

所有论文业务接口都需要：

```http
Authorization: Bearer <token>
```

`token` 可以是：

- 用户登录获得的 JWT。
- 通过 `POST /api/v1/users/apiToken` 换取的长期 API Token。

## 直连接口流程

适合业务后端直接调用。

### 推荐论文题目

```http
POST /api/v1/thesis/titles/recommend
```

根据研究方向、背景、对象或问题描述生成 20 个互不重复的论文题目。接口使用项目统一的 `code`、`message`、`data` 响应结构，题目数组位于 `data` 字段。

示例请求：

```json
{
  "content": "希望研究人工智能在高校个性化教学中的应用，重点关注学习效果、教师角色和实施策略"
}
```

响应中的 `data` 数组固定包含 20 个题目，以下仅节选前三项展示格式：

```json
{
  "code": 200,
  "message": "ok",
  "data": [
    "人工智能赋能高校个性化教学的应用机制研究",
    "高校个性化教学中人工智能应用效果评价研究",
    "人工智能支持下高校教师角色转型与实施策略研究"
  ]
}
```

### 生成大纲

```http
POST /api/v1/thesis/outline
```

示例请求：

```json
{
  "title": "基于协同过滤算法的电影推荐系统设计与实现",
  "target_word_count": 8000,
  "chinese_reference_count": 20,
  "english_reference_count": 5,
  "three_level": true,
  "aboutmsg": ""
}
```

### 提交生成任务

```http
POST /api/v1/thesis/generate
Idempotency-Key: <业务订单号>
```

提交后立即返回 `task_id`，论文生成由 Redis worker 后台执行。

建议新接入方在请求中明确传递以下字段：

```json
{
  "target_word_count": 5000,
  "chinese_reference_count": 8,
  "english_reference_count": 4,
  "aboutmsg": "仅写入已确认的项目事实；未提供测试数据时不得生成实测结论"
}
```

- 大纲、直连论文生成和管理端 `/thesis/outlines` 统一使用 `chinese_reference_count`、`english_reference_count`：分别为非负整数，合计 1–100 篇，默认 25/0。管理端创建大纲时把这两个字段和 `target_word_count` 放在请求顶层；后续订单自动沿用记录快照。
- 已移除 `codetype`、`wxquote`、`language`、`wxnum`、`reference_count`、`include_foreign` 请求字段，不提供旧字段转换；调用方需同步升级。正文默认标注真实文献，代码及语言由模型按课题和已确认技术栈判断；未确认实现必须标为示例或建议。`three_level` 和 `target_word_count` 保持原义。
- 两种语言按指定数量分别检索、筛选，某种语言不足时不会用另一种语言补齐；设为 0 的语言不检索。有限补检后不足仍继续生成，`result_data.reference_quality` 返回目标/实际数量与 `complete/limited/unavailable` 状态，`result_data.quality_warnings` 提供非阻断提示。调用方应提醒用户补充资料，不应把提示转换为失败、退款或自动重试。
- 零文献时返回 `reference_count=0`、`citation_integrity=no_references`，文档明确标记“待补充参考文献”；正文不保留无来源编号。
- 任务完成后从状态接口的 `result_data.effective_config` 核对实际生效值，不要只依赖前端表单回显。
- `result_data.missing_profile_fields` 非空时，成品会显示 `【待补充：字段】`；调用方应在下载前明确提醒用户。
- `result_data.generated_suggestion_fields` 表示未由用户材料确认的生成建议，不应被业务系统展示为实测事实。

### 查询状态

```http
GET /api/v1/thesis/status/{task_id}
```

### 下载本地文件

```http
GET /api/v1/thesis/download/{task_id}
```

该接口返回本地 `.docx` 文件，适合作为兜底下载方式。

## 订单接口流程

适合 `ai-paper-web` 用户使用。

### 查询价格

```http
GET /api/v1/thesis/price
```

返回：

- 当前生成扣费积分。
- 折算金额。
- 当前用户积分余额。

### 生成并保存大纲

```http
POST /api/v1/thesis/outlines
```

保存后返回 `record_id`，用于后续创建订单。

### 创建订单

```http
POST /api/v1/thesis/orders
Idempotency-Key: <前端或业务稳定唯一值>
```

请求中传入：

- `record_id`
- 用户确认后的 `outline`
- 回调地址和回调密钥，可选

创建订单不扣积分。

### 积分支付并启动生成

```http
POST /api/v1/thesis/orders/pay
```

请求：

```json
{
  "order_sn": "AP202606..."
}
```

支付成功后：

1. 扣减用户积分。
2. 写入积分流水。
3. 创建 `paper_generation_tasks`。
4. 任务进入 Redis 队列。

### 查询订单状态

```http
GET /api/v1/thesis/orders/status?order_sn=AP...
```

### SSE 进度推送

```http
GET /api/v1/thesis/orders/events?order_sn=AP...
```

返回 `text/event-stream`，适合前端实时展示生成阶段和进度。

### 获取下载链接

```http
GET /api/v1/thesis/orders/download-url?order_sn=AP...
```

返回：

- `download_url`
- `file_key`
- `storage_provider`
- `local_file_key`
- `local_download_url`

## 回调业务系统

回调配置来源：

1. 请求体中的 `callback_url` / `callback_secret`。
2. 环境变量 `PAPER_CALLBACK_URL` / `PAPER_CALLBACK_SECRET`。

请求体优先级高于环境变量。

回调方式：

```http
POST <callback_url>
X-Internal-Secret: <callback_secret>
Content-Type: application/json
```

成功回调：

```json
{
  "task_id": "abc123",
  "file_key": "paper/abc123/demo.docx",
  "download_url": "https://...",
  "storage_provider": "qiniu",
  "local_file_key": "output/thesis/abc123/demo.docx",
  "local_download_url": "https://api.example.com/output/thesis/abc123/demo.docx",
  "status": "completed",
  "error_msg": ""
}
```

失败回调：

```json
{
  "task_id": "abc123",
  "file_key": "",
  "download_url": "",
  "storage_provider": "",
  "local_file_key": "",
  "local_download_url": "",
  "status": "failed",
  "error_msg": "生成失败，请稍后重试或联系管理员"
}
```

回调最多尝试 3 次，失败不会改变论文任务状态。

## 幂等建议

以下接口建议传 `Idempotency-Key`：

- `POST /api/v1/thesis/generate`
- `POST /api/v1/thesis/orders`

推荐值：

- 业务系统订单号。
- 支付订单号。
- 前端创建订单前生成的稳定 UUID。

不要使用每次请求都变化的随机值，否则无法达到幂等效果。

## 状态说明

订单状态常见值：

| 状态 | 说明 |
| --- | --- |
| `created` | 已创建，未扣积分。 |
| `paid` | 已扣积分，等待生成。 |
| `generating` | 正在生成。 |
| `completed` | 已完成。 |
| `failed` | 最终失败，通常已退积分。 |

任务状态常见值：

| 状态 | 说明 |
| --- | --- |
| `paid` | 已支付待生成。 |
| `generating` | 正在生成。 |
| `completed` | 已完成。 |
| `failed` | 已失败。 |

## 与 wxy-server 对接注意事项

- 保持调用 `ai-paper-api` 的接口路径和请求结构稳定。
- 使用长期 API Token 调用论文接口。
- `PAPER_CALLBACK_SECRET` 两端必须一致。
- 业务系统收到回调后应校验 `X-Internal-Secret`。
- 业务系统应保存 `task_id`、`file_key`、`storage_provider` 和下载链接。
- HTTP 重试时必须复用同一个 `Idempotency-Key`。
