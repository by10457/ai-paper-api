# 接口对接

本文说明业务系统、Web 前端和管理后台如何对接 AI Paper API。

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

### 生成大纲

```http
POST /api/v1/thesis/outline
```

示例请求：

```json
{
  "title": "基于协同过滤算法的电影推荐系统设计与实现",
  "target_word_count": 8000,
  "codetype": "否",
  "language": "否",
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
