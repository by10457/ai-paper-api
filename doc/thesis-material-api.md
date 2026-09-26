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

标题是唯一必填字段，长度为 2-200 个字符。接口不接收学生、学校和导师等封面资料；开题报告、任务书的 DOCX 固定使用“【待补充：学号】”等明显占位，由用户下载后自行填写。提交响应和最终结构化结果仍返回固定的 `missing_profile_fields`，调用方应在下载前提醒用户。开题报告和文献综述支持 `target_word_count` 与 `reference_options`；任务书支持 `topic_type`，三类材料都会检索真实参考资料。

三类接口还可接收 `source_outline`（与论文 `outline_json` 相同的 `OutlineChapter[]` 结构）和 `thesis_config`（公共论文表单快照：`target_word_count`、`three_level`、`aboutmsg`）。传入用户确认的大纲时直接复用；省略时先生成论文大纲，再建立材料自己的 `material_outline`。两份大纲均保存到请求快照与结构化结果，重试复用。开题报告的论文写作提纲严格沿用源大纲的章节顺序；综述和任务书保留各自文档结构。材料篇幅由顶层 `target_word_count` 控制。

`reference_options` 改为分别指定 `chinese_reference_count`、`english_reference_count`，单项允许 0；合计范围分别为开题报告 8–40、文献综述 12–60、任务书 5–30。默认中英文数量分别为 10/5、15/5、10/0。正文默认执行文献标注与引用校验，缺少的语言文献明确提示，不跨语言补齐。已移除 `target_count`、`include_foreign` 和 `thesis_config` 中的 `codetype`、`wxquote`，调用方需同步升级。

```json
{"reference_options": {"chinese_reference_count": 10, "english_reference_count": 5}}
```

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
  "charged_points":20,
  "missing_profile_fields":["school","name","student_no","class_name","major","internal_advisor","year_month"]
}
```

## 状态、事件和下载

```http
GET /api/v1/thesis-materials/tasks/{task_id}
GET /api/v1/thesis-materials/tasks/{task_id}/events
GET /api/v1/thesis-materials/tasks/{task_id}/download
```

任务阶段依次使用：`queued`、`retrieving_references`、`planning`、`generating_sections`、`validating`、`rendering_docx`、`uploading`、`completed`、`failed`。事件接口为 Server-Sent Events；客户端无法保持 SSE 时可按 2-5 秒轮询任务详情。

完成任务的 `result` 为产品对应的结构化 JSON，同时提供 DOCX 下载。开题报告和文献综述的 `word_count` 明确给出目标、容差、实际值、计入字段和排除区块。统一按正文非空白字符统计，汉字、标点、英文字母和数字均逐字符计数；标题、关键词、提纲、计划、参考文献、个人信息和签字审核区不计入。目标总正文允许正负 10% 的验收容差，并为引用规范化保留最多 20 个非空白字符的后处理缓冲；实际上下限随 `word_count` 返回。失败任务返回 `message`/`error_message` 和已退款积分；普通生成错误会自动重试，耗尽重试后幂等退款。

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

开题报告包含研究目的、文献综述、主要内容、重点难点、研究方法、可行性与创新点、与源大纲同层级的写作提纲、进度计划、参考文献和审核区。文献综述包含摘要、关键词、国内外研究、3-6 个主题比较、方法比较、研究不足、趋势、结论和参考文献。任务书包含设计背景、技术栈建议、设计目标、模块任务、进度计划、成果形式、成果要求、主要指标、参考资料和审核区。

参考文献只来自已配置的万方、SerpAPI/Google Scholar、CrossRef 等真实来源。系统以业务主题匹配作为准入门槛，再使用技术主题重合度排序，并过滤撤稿、著录信息不完整和仅技术栈相似但业务无关的记录。目标总量与中外文比例均尽力满足，有限补检仍不足时按实际数量继续生成，不用弱相关文献凑数；任务书优先使用相关中文资料。共享检索预算与降级规则见 [论文生成流程](thesis-generation.md#参考文献)。请求中参考文献数量的范围仍是目标配置范围，不代表实际结果的交付下限。

结构化结果包含 `reference_quality` 和 `quality_warnings`，明确目标数量、实际总数及语言构成。零文献返回空列表，DOCX 明示“待补充参考文献”，综述内容仅作待核实研究方向/检索计划，不声称已有来源支持。引用覆盖校验按实际文献执行，零文献不要求引用；已完成状态不因这些提示而转换为失败。

任务书仅在用户通过 `research_context.additional_requirements` 或 `thesis_config.aboutmsg` 明确给出对应数值指标时，才将其视为已确认要求；单独出现的 Spring Boot 3 等技术版本号不算。模型额外提出的响应时间、并发量、覆盖率、成果字数或演示时长等阈值会在正文中标记“建议值（待导师确认）”，结构化结果通过 `generated_suggestion_fields` 标识 `design_goals`、`deliverable_requirements` 或 `main_indicators` 等对应字段。

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
