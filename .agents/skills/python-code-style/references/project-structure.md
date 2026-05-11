# T-FastApi 分层约定

## 目录职责

| 目录 | 职责 |
| --- | --- |
| `api/` | 接口层，定义路由、依赖、权限、请求参数和响应组装 |
| `api/v1/` | 按业务模块拆分版本化路由文件 |
| `schemas/` | Pydantic 请求体、响应体、统一响应结构 |
| `services/` | 业务逻辑层，不写 HTTP 细节 |
| `models/` | Tortoise-ORM 数据库模型 |
| `core/` | 配置、数据库、Redis、日志、安全等基础设施 |
| `tasks/` | APScheduler 定时任务注册和任务逻辑 |
| `utils/` | 与业务无关、可复用的通用工具 |
| `scripts/` | 一次性脚本、数据修复脚本，不作为线上服务入口 |
| `tests/` | pytest 测试 |

## 新增业务模块流程

1. 在 `models/` 新建或修改 ORM 模型，并到 `core/config.py` 的 `TORTOISE_ORM` 配置中注册。
2. 在 `schemas/` 定义请求和响应结构。
3. 在 `services/` 实现业务逻辑，保持可测试，不依赖 FastAPI `Request`。
4. 在 `api/v1/` 定义路由，只做依赖注入、参数校验、权限检查和调用 service。
5. 在 `api/v1/__init__.py` 注册路由。
6. 修改模型后运行 `uv run aerich migrate --name "<change_name>"` 和 `uv run aerich upgrade`。

## 路由层规则

- 路由函数保持薄层：解析输入、调用 service、返回 schema。
- 不在路由里直接写复杂数据库查询、缓存编排或跨模块业务流程。
- FastAPI `Depends()` 可以写在参数默认值中；项目 Ruff 已忽略 `B008`，这是框架约定。
- 接口响应优先复用 `schemas/common.py` 中的统一响应结构。

## Service 层规则

- Service 函数表达业务动作，例如 `create_user`、`reset_password`、`list_active_orders`。
- Service 层可以调用 models、utils、core 中的基础能力，但不要依赖路由对象。
- 涉及多个外部资源时，明确异常处理、事务边界和重试策略。

## Schema 与 Model 边界

- `models/` 表示数据库结构和 ORM 行为。
- `schemas/` 表示 API 输入输出，不把 ORM 模型直接暴露为响应结构。
- Schema 命名建议按场景区分，例如 `UserCreate`、`UserUpdate`、`UserOut`。

## 配置与基础设施

- 配置统一从 `core/config.py` 的 `settings` 获取，不在业务代码中重复读取 `.env`。
- 数据库连接、Redis 连接、定时任务生命周期放在 `core/` 和 `app.py` 的 lifespan 中维护。
- 日志使用项目已有 Loguru 配置，不在模块里临时创建不一致的日志体系。
