# 论文材料生成接口

本文档描述 `ai-paper-api` 的开题报告、文献综述和任务书接口。接口路径均以 `/api/v1` 为前缀，响应使用项目现有的 `Response` 包装（业务数据位于 `data`）。

## 鉴权与幂等

请求必须携带现有 JWT 或长期 API Token 鉴权头：

```http
Authorization: Bearer <token>
```

三个提交接口支持 `Idempotency-Key`。调用方应在网络重试时复用同一个键；键最长 128 个字符，重复键返回原任务，不会重复创建订单或扣积分。

## 产品与计费

```http
GET /api/v1/thesis-materials/products
```

返回当前用户余额和三类产品的服务端价格。默认每类 20 积分，实际值以接口返回为准。余额不足返回 HTTP `402`。

## 提交任务

```http
POST /api/v1/thesis-materials/proposal-reports
POST /api/v1/thesis-materials/literature-reviews
POST /api/v1/thesis-materials/task-books
```

标题是唯一必填字段，长度为 2-200 个字符。学校、学生、导师和日期等资料均为可选；未提供时，DOCX 使用“某某大学”“某某某”“20XXXXXXXXXX”等明显占位值，便于下载后替换。开题报告和文献综述支持 `target_word_count` 与 `reference_options`；任务书支持 `topic_type`，三类材料都会检索真实参考资料。

最小请求：

```json
{"title":"基于人工智能的校园服务平台设计与实现"}
```

提交响应示例：

```json
{
  "task_id":"a1b2c3d4",
  "order_sn":"TM20260809123456789ABC",
  "document_type":"proposal_report",
  "status":"queued",
  "charged_points":20
}
```

## 状态、事件和下载

```http
GET /api/v1/thesis-materials/tasks/{task_id}
GET /api/v1/thesis-materials/tasks/{task_id}/events
GET /api/v1/thesis-materials/tasks/{task_id}/download
```

任务阶段依次使用：`queued`、`retrieving_references`、`planning`、`generating_sections`、`validating`、`rendering_docx`、`uploading`、`completed`、`failed`。事件接口为 Server-Sent Events；客户端无法保持 SSE 时可按 2-5 秒轮询任务详情。

完成任务的 `result` 为产品对应的结构化 JSON，同时提供 DOCX 下载。失败任务返回 `message`/`error_message` 和已退款积分；普通生成错误会自动重试，耗尽重试后幂等退款。

## 订单

```http
GET /api/v1/thesis-materials/orders?page=1&page_size=10
GET /api/v1/thesis-materials/orders/{order_sn}
```

订单列表只返回当前用户的三类论文材料，不包含论文正文订单。订单详情包含请求快照、结构化结果、阶段、进度、失败原因和下载地址。

管理端使用独立的全量查询接口和页面查看全部用户的材料任务：

```http
GET /api/v1/admin/thesis-material-orders
GET /api/v1/admin/thesis-material-orders/{order_id}
```

## 结果结构

开题报告包含研究目的、文献综述、主要内容、重点难点、研究方法、可行性与创新点、严格三级写作提纲、进度计划、参考文献和审核区。文献综述包含摘要、关键词、国内外研究、3-6 个主题比较、方法比较、研究不足、趋势、结论和参考文献。任务书包含设计背景、技术栈建议、设计目标、模块任务、进度计划、成果形式、成果要求、主要指标、参考资料和审核区。

参考文献只来自已配置的万方、SerpAPI/Google Scholar、CrossRef 等真实来源。系统会过滤撤稿记录，按标题相关度排序、去重并连续编号。开题报告和文献综述按目标数量尽量满足中外文比例，同时设置可交付下限；任务书优先使用与课题直接相关的中文资料。正文引用覆盖不足时会进入局部修复，不要求为了凑编号在段末堆叠全部引用。

## 错误码

常见 HTTP 状态包括：`400` 请求字段或日期范围错误，`401` 未鉴权，`403` 无权访问任务，`404` 任务/订单/文件不存在，`402` 余额不足，`409` 任务尚未完成无法下载，`422` 请求 Schema 校验失败，`500` 生成服务内部错误。错误响应沿用项目现有 `Response`/FastAPI 错误格式。

## 数据隔离与发布

三类材料使用独立的 `paper_material_orders`、`paper_material_generation_tasks` 表，不再写入 `paper_orders` 和 `paper_generation_tasks`。积分流水和模型调用日志通过可空外键关联对应业务订单/任务，论文历史数据保持原样。

全新环境以 `sql/init.sql` 为准。现有环境发布前，应依据 `sql/init.sql` 中的新表及关联字段编制并审查一次性增量 DDL；项目当前未启用正式迁移框架，不要重复执行完整初始化脚本，也不要沿用早期把材料字段塞入论文表的旧方案。

旧版 `/api/v1/paper-materials/*`、`/api/v1/admin/paper-material-orders*`、`/api/v1/writing/*` 和 `/api/v1/admin/writing-orders*` 暂时保留为隐藏兼容入口，不写入 OpenAPI。新接入与现有前端统一使用 `thesis-materials` 路径。

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
