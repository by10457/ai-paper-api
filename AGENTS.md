# ai-paper-api AI 开发入口

本文件只保留仓库级入口、项目事实和跨模块不变量。具体编码与测试细则由 `.agents/skills/` 维护，避免在多处复制后产生冲突。

## 开始任务

1. 完整读取 `.agents/skills/SKILL.md`，再按其路由加载当前任务需要的 skill；Markdown 链接不会自动载入内容。
2. 功能开发、修复、重构、调试、配置调整或代码审查，读取 `.agents/skills/coding-guidelines/SKILL.md`。
3. 编写、修改或审查 Python，读取 `.agents/skills/python-code-style/SKILL.md` 以及其中要求的 `references/code-style.md`；按任务再读取项目结构或工具链参考。
4. 新增、修改、迁移、审查或删除测试与 fixture，读取 `.agents/skills/test-guidelines/SKILL.md`。
5. 执行修改前运行 `rtk git status --short`，识别并保留用户已有改动。
6. skill 缺失或不可读时，停止受其约束的修改并报告，不凭记忆补写项目规范。

## 项目基线

- Python `>=3.13`，依赖和命令环境使用 `uv`。
- FastAPI + Pydantic，Tortoise-ORM + MySQL，`redis.asyncio` + APScheduler。
- LLM 层支持 OpenAI 兼容协议、Anthropic、Gemini；图片、参考文献和回调还会访问外部 HTTP 服务。
- 论文产物使用 python-docx、Mermaid CLI、matplotlib，并支持 local、七牛、MinIO、腾讯云 COS 存储。
- 质量工具为 pytest/pytest-asyncio、Ruff 和 Mypy。
- 本仓库 shell 命令统一加 `rtk` 前缀，例如 `rtk uv run pytest -q`。

## 代码地图

```text
api/                    FastAPI 路由与认证依赖
core/                   配置、MySQL、Redis、日志和安全
llm/                    模型客户端、调用日志与提示词
models/                 Tortoise ORM 模型
schemas/                Pydantic 请求/响应结构
services/admin/         管理后台业务
services/thesis/        论文业务、内容、生成、文档、图片和存储
tasks/                  scheduler、worker 与任务恢复入口
tests/                  横切模块测试；论文领域测试位于 tests/thesis/
sql/init.sql             当前阶段统一维护的初始化表结构
public/                 前端静态产物和本地论文文件
doc/                    部署、生成流程、模型、存储、接口与运维文档
```

## 跨模块不变量

- API 层只处理参数、依赖和响应组装；业务进入 `services/`，ORM 进入 `models/`，输入输出结构进入 `schemas/`。
- 修改数据库字段时同步检查 ORM model、`sql/init.sql`、schema/service/API 以及实际数据库升级方式；当前阶段不要新增零散补丁 SQL。
- 模型 API Key、Base URL 和模型名由管理后台的 `model_configs` 管理，不写入代码、测试 fixture 或普通配置示例。
- 论文提交必须保持幂等；订单流程必须保持扣积分、重试、最终失败退款的一致性。
- Redis 队列需要保持 ready/delayed/去重语义；任务状态以 Redis 为主、本地 `status.json` 为兜底。
- 论文先生成本地文件；远端存储失败应保留本地下载兜底。私有存储链接可能过期，持久化 provider 与 file key，按需生成下载链接。
- API 可以多 worker，但 scheduler/论文 worker 只能有一个实例；修改 `APP_ROLE`、lifespan 或部署脚本时检查重复执行风险。
- 不提交 `.env`、真实账号、JWT/API Token、模型 Key、数据库密码、对象存储密钥、Cookie、验证码、抓包或含个人信息的生成产物。
- 单元测试不得隐式访问真实 MySQL、Redis、模型服务、参考文献服务、对象存储、回调地址或公网。
- `public/` 含构建产物和运行时论文文件；除非任务明确要求，不手工修改压缩静态资源或提交生成文件。

## 工作方式

- 只修改完成当前任务必需的文件，不顺手重构、格式化或删除相邻代码。
- 能从代码、配置、测试和文档确认的事实先自行确认；会改变接口、数据或部署行为的不确定项再向用户说明。
- 修 bug 优先建立最小复现；修改业务行为时同时覆盖成功、失败或降级路径。
- 新增依赖、模块或抽象前确认现有实现无法小步解决，避免为一次使用构建框架。
- 行为、配置或运维方式变化时，同步更新最接近该主题的文档，不复制同一说明到多个文件。

## 验证与交付

先运行最小相关检查，再按影响范围扩大：

```bash
rtk uv run ruff check <changed-paths>
rtk uv run mypy <changed-python-paths>
rtk uv run pytest <related-test-paths> -q
rtk uv run pytest -q
rtk uv run python -c "from app import app; app.openapi(); print('openapi ok')"
```

- 纯文档或 skill 修改：检查 frontmatter、链接、目录和命令是否与仓库一致；skill 使用 `quick_validate.py` 验证。
- API、schema、路由或依赖变化：运行相关测试和 OpenAPI 生成检查。
- 队列、worker、订单、状态、存储、LLM 或文档生成变化：运行对应测试；跨模块流程变化再跑全量 pytest。
- Mypy 当前并非全仓绿色基线；不得隐藏结果。区分本次新增问题和既存问题，并确保改动不扩大错误范围。
- 最终回复说明修改内容、实际运行的命令与结果、未运行项、既存失败和残余风险。

## 指令优先级

- 更靠近目标文件的 `AGENTS.md` 或 `AGENTS.override.md` 可以补充或覆盖本文件；同目录下 override 优先。
- 系统、开发者和用户当前指令高于仓库指令；冲突时遵循更高优先级并明确说明。
- 修改本文件只影响之后重新加载指令链的运行；需要验证新规则时开启新会话。
