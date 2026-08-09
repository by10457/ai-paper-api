# 学术材料生成接口

本文档描述 `ai-paper-api` 的开题报告、文献综述和任务书接口。接口路径均以 `/api/v1` 为前缀，响应使用项目现有的 `Response` 包装（业务数据位于 `data`）。

## 鉴权与幂等

请求必须携带现有 JWT 或长期 API Token 鉴权头：

```http
Authorization: Bearer <token>
```

三个提交接口支持 `Idempotency-Key`。调用方应在网络重试时复用同一个键；键最长 128 个字符，重复键返回原任务，不会重复创建订单或扣积分。

## 产品与计费

```http
GET /api/v1/writing/products
```

返回当前用户余额和三类产品的服务端价格。默认每类 20 积分，实际值以接口返回为准。余额不足返回 HTTP `402`。

## 提交任务

```http
POST /api/v1/writing/proposal-reports
POST /api/v1/writing/literature-reviews
POST /api/v1/writing/task-books
```

标题是唯一必填字段，长度为 2-200 个字符。学校、学生、导师和日期字段缺失时保持空白，服务不会代填。开题报告和文献综述支持 `target_word_count` 与 `reference_options`；任务书支持 `topic_type`，不执行文献检索。

最小请求：

```json
{"title":"基于人工智能的校园服务平台设计与实现"}
```

提交响应示例：

```json
{
  "task_id":"a1b2c3d4",
  "order_sn":"W202608091234",
  "document_type":"proposal_report",
  "status":"queued",
  "charged_points":20
}
```

## 状态、事件和下载

```http
GET /api/v1/writing/tasks/{task_id}
GET /api/v1/writing/tasks/{task_id}/events
GET /api/v1/writing/tasks/{task_id}/download
```

任务阶段依次使用：`queued`、`retrieving_references`、`planning`、`generating_sections`、`validating`、`rendering_docx`、`uploading`、`completed`、`failed`。事件接口为 Server-Sent Events；客户端无法保持 SSE 时可按 2-5 秒轮询任务详情。

完成任务的 `result` 为产品对应的结构化 JSON，同时提供 DOCX 下载。失败任务返回 `message`/`error_message` 和已退款积分；普通生成错误会自动重试，耗尽重试后幂等退款。

## 订单

```http
GET /api/v1/writing/orders?page=1&page_size=10
GET /api/v1/writing/orders/{order_sn}
```

订单列表只返回三类学术材料，不包含既有 `thesis` 订单。订单详情包含请求快照、结构化结果、阶段、进度、失败原因和下载地址。

## 结果结构

开题报告包含 `research_purpose`、`research_status_and_trends`、`key_points`、`difficulties`、`research_methods`、`schedule`、`references` 和空白 `approval`。文献综述包含摘要、关键词、国内外研究、3-6 个主题比较、方法比较、研究不足、趋势、结论和参考文献。任务书包含设计背景、技术栈建议、5-10 个设计目标、4-8 个模块任务、五阶段计划、成果形式、成果要求和空白审核区。

参考文献只来自已配置的万方、SerpAPI/Google Scholar、CrossRef 等真实来源。系统会按标题去重、连续编号，并校验每条文献至少被正文引用一次。开题报告默认必须达到 10 篇中文和 5 篇英文文献，最低交付为 6 篇中文和 2 篇英文；文献综述默认必须达到 14 篇中文和 6 篇英文，最低交付为 8 篇中文和 4 篇英文。目标数量调整时按中文约三分之二、英文约三分之一计算；低于相应交付下限时任务失败退款，不使用模型生成的文献条目补数。

## 错误码

常见 HTTP 状态包括：`400` 请求字段或日期范围错误，`401` 未鉴权，`403` 无权访问任务，`404` 任务/订单/文件不存在，`402` 余额不足，`409` 任务尚未完成无法下载，`422` 请求 Schema 校验失败，`500` 生成服务内部错误。错误响应沿用项目现有 `Response`/FastAPI 错误格式。

生产发布前请先执行 `sql/20260809_academic_writing.sql`，再发布 API 和 Worker。脚本只增加文档类型、结构化结果字段和索引，并将历史记录回填为 `thesis`。

## 小程序业务后端

`edu-sys-server` 对小程序提供以下接口，并复用学校项目价格、会员优惠、用户积分、订单和退款账本：

```http
POST /ai-writing/proposal-reports
POST /ai-writing/literature-reviews
POST /ai-writing/task-books
GET  /ai-writing/projects
GET  /ai-writing/orders
GET  /ai-writing/orders/{orderId}
GET  /ai-writing/orders/{orderId}/download
```

提交请求使用 camelCase，额外必填 `expectedPayablePoints` 作为价格变化保护，并同样接受 `Idempotency-Key`。Java 侧的订单和任务 ID 始终序列化为字符串。上游 Python 返回 `402` 时，Java 将本地订单标记失败并幂等退款；最终生成失败时，Python 服务账号额度与 Java 小程序用户积分分别在各自账本退款。
