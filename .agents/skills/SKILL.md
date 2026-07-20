---
name: edu-sys-spider-skills
description: edu-sys-spider 项目的 skills 路由入口。在仓库内开始功能开发、代码修改、重构、调试、审查、配置或测试任务时必须使用，用于确定并加载当前任务需要遵循的具体规范。
---

# edu-sys-spider 技能入口

本文件是 `.agents/skills/` 的总入口。修改本仓库代码时，必须按下面的技能职责加载具体 skill，不要只读这个索引就开始编码。

## 技能列表

| 技能 | 路径 | 使用场景 |
| --- | --- | --- |
| AI 编码行为准则 | `.agents/skills/coding-guidelines/SKILL.md` | 做功能开发、重构、修 bug、review、迁移旧项目代码时使用，约束工作方式、改动范围和验证习惯。 |
| Python 代码风格 | `.agents/skills/python-code-style/SKILL.md` | 编写或审查 Python/FastAPI/Tortoise/Pydantic 代码时使用，约束代码风格、分层、类型和工具链。 |
| 测试开发规范 | `.agents/skills/test-guidelines/SKILL.md` | 新增、修改、迁移、归类、审查或删除 pytest 测试与 fixture 时使用，约束目录、隔离、脱敏、生命周期和验证流程。 |

## 强制加载顺序

1. 涉及代码实现、重构或 bug 修复时，先读 `coding-guidelines/SKILL.md`。
2. 涉及 Python 代码时，再读 `python-code-style/SKILL.md`。
3. 只要要写 Python 代码，必须继续读取 `python-code-style/references/code-style.md`，不要只依赖 `python-code-style/SKILL.md` 的摘要。
4. 涉及测试或 fixture 时，再读 `test-guidelines/SKILL.md`；删除测试前必须按其中的证据要求审计。

## 强制提醒

- `python-code-style/references/code-style.md` 是本项目代码风格的细则来源，AI 经常遗漏的命名、异常、类型、函数拆分、模块组织规则都在这里。
- 本项目偏好“核心流程集中、少量函数讲清楚一个功能”，不要把一个业务工具拆成大量小函数。
- Python 函数上方需要中文单行说明；函数内部 docstring 需要说明参数、返回值和业务边界。
- 测试必须按 API、基础设施、服务、学校和工具分类；真实响应 fixture 入库前必须脱敏。
- 如果规则冲突，以任务范围内更具体的文件为准：测试任务遵循 `test-guidelines/SKILL.md`，Python 风格遵循 `code-style.md`，通用流程遵循 `coding-guidelines/SKILL.md`；具体 skill 均优先于本索引。
- 执行本仓库命令时遵循项目环境要求，命令前使用 `rtk` 前缀，例如 `rtk uv run pytest`。
