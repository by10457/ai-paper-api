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

必填字段为 `title`、`source_outline` 和 `thesis_config`。三类材料均以用户确认的论文大纲为研究范围，不再支持仅传标题后重新生成大纲。开题报告打印同一份写作提纲；综述、任务书只把大纲作为生成参考，保留各自文档结构。

`thesis_config` 是大纲阶段的公共配置快照：`target_word_count`、`aboutmsg`、`chinese_reference_count`、`english_reference_count`。文献数量只从此处读取，单项允许 0、合计 1–100 篇，不再受材料类型独立限额约束。前端自动传递已确认配置，不重复要求用户填写。已移除 `reference_options`、`schedule_options`，旧字段会被拒绝，调用方须同步升级。

材料自身的 `target_word_count` 独立设置：开题报告默认 4000（2500–12000），综述默认 6000（3500–20000），任务书默认 2000（1000–6000）。可选的 `research_context` 用于补充材料特有要求；不填写时沿用大纲阶段的研究要求。

进度计划使用相对周次，不接收具体日期；开题报告与任务书统一按 16 周分配阶段。接口不收集学生、学校、导师信息；DOCX 使用明显的“【待补充】”占位，响应的 `missing_profile_fields` 提醒下载后补全。

请求示例（开题报告）：

```json
{
  "title": "校园服务平台设计与实现",
  "source_outline": [
    {"chapter": "绪论", "sections": [{"name": "研究背景", "abstract": "说明研究背景与意义"}]}
  ],
  "thesis_config": {
    "target_word_count": 8000,
    "aboutmsg": "围绕校园服务流程",
    "chinese_reference_count": 20,
    "english_reference_count": 5
  },
  "target_word_count": 4000
}
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

完成任务的 `result` 为产品对应的结构化 JSON，同时提供 DOCX 下载。三类材料的 `word_count` 明确给出目标、容差、实际值、计入字段和排除区块。统一按正文非空白字符统计，汉字、标点、英文字母和数字均逐字符计数；标题、关键词、提纲、计划、参考文献、个人信息和签字审核区不计入。目标总正文允许正负 10% 的验收容差，并为引用规范化保留最多 20 个非空白字符的后处理缓冲；实际上下限随 `word_count` 返回。失败任务返回 `message`/`error_message` 和已退款积分；普通生成错误会自动重试，耗尽重试后幂等退款。

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

参考文献只来自已配置的万方、SerpAPI/Google Scholar、CrossRef 等真实来源。系统以业务主题匹配作为准入门槛，再使用技术主题重合度排序，并过滤撤稿、著录信息不完整和仅技术栈相似但业务无关的记录。目标总量与中外文比例均尽力满足，有限补检仍不足时按实际数量继续生成，不用弱相关文献凑数；三类材料均继承大纲的中英文数量目标。共享检索预算与降级规则见 [论文生成流程](thesis-generation.md#参考文献)。请求中参考文献数量的范围仍是目标配置范围，不代表实际结果的交付下限。

结构化结果包含 `reference_quality` 和 `quality_warnings`，明确目标数量、实际总数及语言构成。零文献返回空列表，DOCX 明示“待补充参考文献”，综述内容仅作待核实研究方向/检索计划，不声称已有来源支持。引用覆盖校验按实际文献执行，零文献不要求引用；已完成状态不因这些提示而转换为失败。

任务书仅在用户通过 `research_context.additional_requirements` 或 `thesis_config.aboutmsg` 明确给出对应数值指标时，才将其视为已确认要求；单独出现的 Spring Boot 3 等技术版本号不算。模型额外提出的响应时间、并发量、覆盖率、成果字数或演示时长等阈值会在正文中标记“建议值（待导师确认）”，结构化结果通过 `generated_suggestion_fields` 标识 `design_goals`、`deliverable_requirements` 或 `main_indicators` 等对应字段。

## 材料正文与版式质量约束

- 源论文大纲限定研究范围，不替代综述自身的章节结构；摘要和引言须描述当前材料。
- 仅有题名元数据时，不得断言原文方法、效果或研究局限。引用规范化在原句位置保留枚举结构，不删除枚举项后集中追加编号；重复规范化不得累积重复句。
- 单字段篇幅是软预算，重写后允许在最终字段下限内波动，正文总字数仍按产品范围验收。机械压缩须保留关联的枚举句，不能输出断号分类。
- 局部篇幅修复优先保留已有内容：任务书最多修复 3 次背景或模块职责，开题报告和综述在字段修复后最多进行 4 次总量差额修复；不为微小字段预算偏差重建整个结果。修复后仍执行总字数硬校验。
- 综述使用“国内研究现状”和“国外研究现状”标题，依据可核验的研究地域组织资料，不把英文来源自动当作国外研究；地域无法确认时明确资料不足。仅核验书目元数据不能证明正文观点已获原文支持；开题报告、综述有文献时通过 `reference_evidence_limited` 和 `reference_evidence_notice` 明示此限制。
- 任务书参考文献逐条使用不可拆分表格行，审核签字行也避免跨页拆分。
- 任务书的 `role` 表示任务目的或研究对象，`boundary` 表示研究范围，不是提示词约束。隐私占位、JSON 输出等内部规则不属于任务成果。
- 材料使用页脚页码；任务书成果区采用窄标签列和宽内容列，计划表跨页重复表头；单周计划不重复显示相同起止周。
- 共享文献格式化优先使用明确来源类型，不能因会议或图书容器名称非空就标为期刊。

## 错误码

常见 HTTP 状态包括：`400` 请求字段错误，`401` 未鉴权，`403` 无权访问任务，`404` 任务/订单/文件不存在，`402` 余额不足，`409` 任务尚未完成无法下载，`422` 请求 Schema 校验失败，`500` 生成服务内部错误。错误响应沿用项目现有 `Response`/FastAPI 错误格式。

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
