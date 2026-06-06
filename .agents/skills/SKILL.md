---
name: ai-paper-api-skills
description: AI Paper API 后端项目的 skill 总入口。凡是修改、审查、调试或解释 ai-paper-api 代码，尤其是 services、api、schemas、models、core、tasks 中的 Python 代码时，都应先读取本入口，再按需引入 coding-guidelines 与 python-code-style。
---

# AI Paper API Skill 总入口

这个文件是 `/home/by/wxy/ai-paper-api` 的根级 skill 索引，用于避免只依赖零散子目录 skill，导致 AI 编程时遗漏项目规范。

## 使用顺序

处理本项目后端代码时，按以下顺序读取规范：

1. `coding-guidelines/SKILL.md`
   - 约束 AI 编码行为：先确认现状、小步改动、避免过度工程化、保护用户已有改动。
   - 适用于所有修复、重构、review、配置调整和测试补充。

2. `python-code-style/SKILL.md`
   - 约束 Python 代码风格：中文注释、类型标注、docstring、FastAPI 分层、Ruff/Mypy/pytest 验证。
   - 修改 Python 文件时必须遵循。

3. `python-code-style/references/code-style.md`
   - 当任务涉及注释、docstring、函数拆分、变量命名、类型注解或异常处理时读取。

4. `python-code-style/references/project-structure.md`
   - 当任务涉及新增模块、跨层调用、服务边界、API/schema/model/service 放置位置时读取。

5. `python-code-style/references/tooling.md`
   - 当任务涉及 Ruff、Mypy、pytest、uv、依赖管理或验证命令时读取。

## services 目录重点规范

`services/` 是本项目业务核心。修改这里时尤其注意：

- 文件顶部应有中文模块 docstring，说明该文件的业务职责和边界。
- 公共函数、复杂业务函数、跨模块调用入口应写中文 docstring。
- 函数参数和返回值应写明确类型标注，不让 `Any` 在业务内部扩散。
- 变量命名应体现业务含义，避免 `data`、`res`、`tmp` 这类含义不清的名称长期存在。
- 注释解释“为什么这样做”和业务约束，不逐行复述代码。
- 不在 `services/` 中混入路由层职责；路由层只做参数、依赖、权限和响应组装。
- 外部接口、LLM、存储、数据库、Redis 等边界处要记录必要日志，并收窄返回类型。
- 涉及支付、扣积分、生成任务、回调、队列、状态恢复等流程时，优先保留幂等和补偿语义。

## 验证要求

- 只改 skill 或文档：检查 frontmatter、路径和描述是否与项目一致。
- 改 Python 文件：至少运行 `uv run ruff check <changed-files>`。
- 改类型签名、schema、核心 service：加跑相关 pytest；必要时运行 Mypy。
- 无法运行验证时，最终回复必须说明原因和残余风险。
