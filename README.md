# AI Paper API

AI Paper API 是一个自研论文生成服务，核心目标是替代不稳定的第三方论文 API，并作为独立服务同时支撑：

- `/home/by/wxy/wxy-server` 等业务后端通过 Token 调用论文生成能力。
- `/home/by/wxy/ai-paper-web` 管理后台维护用户、积分、订单、模型配置和生成日志。
- 前端用户通过 Web 页面生成大纲、确认大纲、扣积分并生成 Word 论文。

项目基于 FastAPI、Tortoise-ORM、Redis、APScheduler、LangChain、python-docx、Mermaid CLI、matplotlib 和对象存储 SDK 构建。

## 核心能力

- 用户账号、JWT 登录、长期 API Token。
- 积分扣费、积分流水、论文订单、失败退费和后台人工处理。
- 论文大纲生成、正文生成、摘要/关键词/致谢生成、参考文献检索。
- Mermaid 图、matplotlib 图表、AI 插图渲染和 Word 文档组装。
- Redis 队列驱动的论文生成 worker，支持幂等提交、失败重试和进程重启补偿。
- 模型配置在管理后台维护，支持 OpenAI 兼容协议、Anthropic Messages、Gemini generateContent、OpenAI Images、Gemini 图片生成。
- 存储支持 local、七牛云、MinIO、腾讯云 COS；本地文件始终保留为兜底。
- 生成完成后回调上游业务系统，并返回存储类型、文件 key 和下载链接。

## 目录结构

```text
.
├── api/                    # FastAPI 路由层
│   ├── dependencies/       # JWT、API Token、管理员权限等依赖
│   └── v1/                 # v1 接口：auth、user、thesis、admin、health
├── core/                   # 配置、MySQL、Redis、日志、安全等基础设施
├── doc/                    # 项目专题文档
├── llm/                    # 大模型客户端、调用日志、提示词
├── models/                 # Tortoise ORM 模型
├── schemas/                # Pydantic 请求/响应模型
├── services/
│   ├── admin/              # 管理后台业务
│   └── thesis/
│       ├── business/       # 订单、积分、回调
│       ├── content/        # 大纲、正文、摘要、参考文献内容生成
│       ├── document/       # Word 文档排版与组装
│       ├── generation/     # Redis 队列、任务状态、生成流水线
│       ├── image/          # Mermaid、图表和 AI 插图渲染
│       └── storage/        # local/qiniu/minio/cos 存储
├── sql/init.sql            # 当前初始阶段的统一建表 SQL
├── tasks/                  # 定时任务和论文生成 worker 入口
├── public/                 # 前端静态资源和本地论文产物
├── Dockerfile              # 分层构建镜像，包含 Chromium、mmdc 和 Python 依赖
├── start.sh                # Docker 部署脚本
├── app.py                  # FastAPI 应用实例和生命周期
└── main.py                 # Uvicorn 启动入口
```

## 文档导航

详细说明集中在 `doc/`：

- [启动与部署](doc/startup-and-deployment.md)
- [论文生成流程](doc/thesis-generation.md)
- [AI 模型配置](doc/ai-model-config.md)
- [存储配置](doc/storage-config.md)
- [接口对接](doc/api-integration.md)
- [运维与排查](doc/operations.md)

服务内部模块边界说明：

- [论文内容生成说明](services/thesis/content/README.md)
- [论文图片生成与渲染说明](services/thesis/image/README.md)
- [论文文档存储说明](services/thesis/storage/README.md)

## 本地快速启动

准备 MySQL 和 Redis 后执行：

```bash
cp .env.example .env
uv sync
mysql -u root -p < sql/init.sql
uv run python main.py
```

默认访问：

- API 服务：`http://localhost:10462`
- OpenAPI 文档：`http://localhost:10462/docs`
- 前端静态页：`http://localhost:10462/index.html`

`sql/init.sql` 会初始化两个默认用户：

| 用户名 | 角色 | 默认密码 |
| --- | --- | --- |
| `admin` | 管理员 | `demo123456` |
| `by10457` | 普通用户 | `demo123456` |

这些密码只用于本地初始化和测试环境。生产环境导入初始化 SQL 后，应立即在管理后台或数据库中重置默认密码。

本地开发常用配置：

```env
APP_DEBUG=true
APP_RELOAD=false
APP_PORT=10462
MYSQL_HOST=127.0.0.1
REDIS_HOST=127.0.0.1
SCHEDULER_ENABLED=true
```

`APP_DEBUG=true` 时，API 固定 1 个 Uvicorn worker，并在 FastAPI lifespan 中启动定时任务和论文 worker，方便本机调试。

## Docker 部署

生产部署通常使用：

```bash
ENV_FILE=.env.docker sh start.sh
```

常用模式：

```bash
# 常规部署：复用 runtime-base，只重建业务代码层
ENV_FILE=.env.docker sh start.sh

# 依赖或系统运行环境变化时重建 runtime-base
BUILD_MODE=deps ENV_FILE=.env.docker sh start.sh

# 强制完整构建
BUILD_MODE=full ENV_FILE=.env.docker sh start.sh

# 不构建，直接用已有镜像重建容器
BUILD_MODE=none ENV_FILE=.env.docker sh start.sh
```

生产建议配置：

```env
APP_DEBUG=false
WEB_CONCURRENCY=4
APP_ROLE=auto
SCHEDULER_ENABLED=true
BACKEND_CORS_ORIGINS=https://paper.example.com
HOST_PUBLIC_DIR=/data/server/ai-paper-api/public
HOST_LOG_DIR=/data/server/ai-paper-api/logs
```

`APP_ROLE=auto` 会在生产环境解析为 `all`：同一个容器内启动 API 进程和一个独立 scheduler/worker 进程。API 可以多 worker，scheduler/worker 仍只有一份，避免定时任务重复执行。

更多部署细节见 [启动与部署](doc/startup-and-deployment.md)。

## 论文生成入口

对外论文接口统一挂载在：

```text
/api/v1/thesis
```

两种调用形态：

1. 直连接口：适合业务系统直接调用。
   - `POST /api/v1/thesis/outline`
   - `POST /api/v1/thesis/generate`
   - `GET /api/v1/thesis/status/{task_id}`
   - `GET /api/v1/thesis/download/{task_id}`

2. 订单接口：适合 Web 用户使用。
   - `POST /api/v1/thesis/outlines`
   - `POST /api/v1/thesis/orders`
   - `POST /api/v1/thesis/orders/pay`
   - `GET /api/v1/thesis/orders/status`
   - `GET /api/v1/thesis/orders/events`
   - `GET /api/v1/thesis/orders/download-url`
   - `GET /api/v1/thesis/orders`
   - `GET /api/v1/thesis/orders/detail`

认证方式：

```http
Authorization: Bearer <JWT 或 API Token>
```

外部业务系统应使用 `Idempotency-Key` 请求头传入本地业务订单号，避免 HTTP 重试导致重复扣费或重复生成。

更多请求字段和状态说明见 [接口对接](doc/api-integration.md)。

## AI 模型配置

模型 API Key、Base URL 和模型名不放在 `.env`，统一在管理后台“模型配置”页面维护，并保存到 `model_configs` 表。

用途说明：

| 用途 | 说明 |
| --- | --- |
| `outline` | 大纲生成、摘要/致谢、参考文献关键词提取等短文本任务。 |
| `fulltext` | 论文正文长文本生成。 |
| `figure` | AI 插图生成。 |
| `default` | 文本模型兜底配置。 |

支持的文本协议：

- `openai` 或 OpenAI Chat Completions 兼容协议。
- `anthropic` / `claude` / `claude-messages`。
- `gemini` / `gemini-generate-content` / `google-generate-content`。

支持的图片协议：

- `gemini-generate-content` / `google-generate-content`。
- `openai-image-generations`。

更多配置示例见 [AI 模型配置](doc/ai-model-config.md)。

## 参考文献来源

参考文献通过环境变量选择来源：

```env
REFERENCE_PROVIDER_MODE=wfapi
```

可选值：

| 模式 | 说明 |
| --- | --- |
| `wfapi` | 中英文参考文献都使用万方开放平台。默认模式，成本更可控。 |
| `serpapi` | 中英文参考文献都使用 SerpAPI Google Scholar，并通过 CrossRef 补全。 |
| `mixed` | 中文使用万方，英文使用 SerpAPI。 |

## 文件存储

论文文件先生成到：

```text
public/output/thesis/{task_id}
```

然后按 `STORAGE_PROVIDER` 上传远端：

```env
STORAGE_PROVIDER=local   # local / qiniu / minio / cos
```

远端上传失败不会让论文任务失败，系统会降级使用本地文件下载链接。更多说明见 [存储配置](doc/storage-config.md)。

## 常用验证命令

```bash
uv run ruff check .
uv run pytest tests/ -q
uv run python main.py
```

Docker 部署后健康检查：

```bash
curl http://127.0.0.1:10462/api/v1/health
docker logs -f ai-paper-api
```

## 重要约定

- `.env`、`.env.docker`、真实 API Key、数据库密码、对象存储密钥不得提交。
- 当前初始阶段统一维护 `sql/init.sql`，不要再新增补丁式 SQL 文件。
- 修改模型字段后，需要同步 ORM 模型、`sql/init.sql` 和实际数据库。
- 前端构建产物可以放到 `public/`，生产也可以通过 `HOST_PUBLIC_DIR` 挂载宿主机目录到容器 `/app/public`。
- 生产多副本部署时，只能有一个 scheduler/worker 实例；多个 API 实例应使用 `APP_ROLE=api`，单独保留一个 `APP_ROLE=scheduler`。
