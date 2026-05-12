# AI Paper API

> 基于 FastAPI + Tortoise-ORM + Redis + APScheduler 的论文业务后端服务

## 目录结构

```
.
├── main.py                 # 启动入口
├── app.py                  # FastAPI 实例 + 生命周期（连接初始化/关闭、开发环境定时任务）
├── pyproject.toml          # uv 依赖管理 + aerich 迁移工具配置 + pytest 配置
├── uv.lock                 # uv 锁文件
├── .env.example            # 环境变量模板（提交到仓库）
├── .env.docker             # 实际docker运行环境变量（不提交！）
├── .env                    # 实际环境变量（不提交！）
│
├── api/                    # 接口层：路由定义，只做参数校验和调用 service
│   ├── dependencies/       # FastAPI 依赖注入（获取当前用户、权限校验等）
│   │   └── auth.py         # 认证与权限依赖
│   └── v1/
│       ├── auth.py         # 认证路由
│       ├── health.py       # 健康检查路由
│       └── user.py         # 用户路由
│
├── core/                   # 核心基础设施
│   ├── config.py           # 配置中心（读取 .env，全局唯一 settings 对象）
│   ├── database.py         # MySQL 连接管理（Tortoise-ORM）
│   ├── redis.py            # Redis 连接管理（redis-py asyncio）
│   ├── logger.py           # 日志配置（loguru）
│   └── security.py         # JWT / 密码哈希
│
├── models/                 # ORM 数据库模型（与数据表一一对应）
├── schemas/                # Pydantic 请求/响应类型定义
├── services/               # 业务逻辑层（不含 HTTP 相关代码）
├── middlewares/            # 全局中间件（请求日志、请求 ID、耗时统计等）
│
├── tasks/                  # 定时任务
│   ├── scheduler.py        # 调度器实例 + 任务注册函数
│   └── runner.py           # 定时任务独立运行入口
│
├── utils/                  # 通用工具函数
├── scripts/                # 一次性脚本（数据修复等，不部署到生产）
├── sql/                    # SQL 初始化文件（建库、初始数据）
├── public/                 # 静态资源（前端页面、图片等）
├── tests/                  # 测试
└── logs/                   # 日志文件（.gitignored）
```

## 快速开始

```bash
# 1. 复制环境变量并填写
cp .env.example .env

# 2. 同步依赖
uv sync

# 3. 初始化数据库迁移（首次）
uv run aerich init -t core.database.TORTOISE_ORM
uv run aerich init-db

# 4. 启动
uv run python main.py
```

默认情况下，应用启动会尝试连接 MySQL 和 Redis；如果连接失败，只会在控制台打印未连接警告，应用仍会继续启动。这样基于模板开发纯 API、纯静态页或暂时不使用数据库/缓存的项目，也可以先跑起来。真正调用依赖 MySQL/Redis 的接口时，仍需要保证对应服务可用。

应用启动不会自动创建表结构。表结构推荐通过 aerich 迁移维护；如果只是本地临时调试，也可以设置 `DB_GENERATE_SCHEMAS=true` 让 Tortoise 在启动时自动创建缺失表。

生产环境可在 `.env` 中设置 `APP_DEBUG=false`，并按服务规格显式设置 `WEB_CONCURRENCY` 控制 worker 进程数。未设置 `WEB_CONCURRENCY` 时，模板默认使用 `min(CPU 核心数, 4)`，避免容器或多核机器上自动开出过多进程。

## 常用命令

```bash
# 生成迁移文件（修改 models 后执行）
uv run aerich migrate --name "simplify_user_table"

# 应用迁移
uv run aerich upgrade

# 运行测试
uv run pytest tests/ -v
```

## 内置接口演示

启动后访问 `/`，会自动打开 `public/index.html`，可以在静态页面里完成用户注册、登录、带 JWT 查询当前用户、更新当前用户信息。

当前模板只保留一张 `users` 表，接口示例聚焦普通用户认证流程：

- `POST /api/v1/users/register`：注册用户
- `POST /api/v1/auth/login`：登录并获取 JWT
- `GET /api/v1/users/userInfo`：带 JWT 查询当前用户
- `POST /api/v1/users/updateInfo`：带 JWT 更新当前用户

## Docker 部署

模板提供了 `Dockerfile`、`.dockerignore` 和 `start.sh`，用于构建镜像、启动容器、挂载日志目录。

### 1. 准备环境变量

```bash
cp .env.example .env
```

如果 MySQL 和 Redis 安装在宿主机，容器内不能继续使用 `127.0.0.1` 连接宿主机服务，建议改成：

```env
MYSQL_HOST=host.docker.internal
REDIS_HOST=host.docker.internal
```

`start.sh` 默认会给容器添加 `host.docker.internal -> host-gateway` 映射，适合 Linux/WSL Docker 环境。

如果 MySQL 和 Redis 也是 Docker 容器，建议把它们和应用容器放到同一个 Docker network，并在 `.env` 中使用容器名或服务名：

```env
MYSQL_HOST=mysql
REDIS_HOST=redis
```

### 2. 启动应用容器

```bash
sh start.sh
```

常用自定义参数：

```bash
# 默认使用 .env 中的 APP_PORT=10462。
# APP_DEBUG=true 或 SCHEDULER_ENABLED=false 时只启动 API。
sh start.sh

# 生产环境通常使用 .env.docker，一个容器内同时托管 API 和定时任务进程
ENV_FILE=.env.docker sh start.sh

# 如需改成宿主机其他端口，可显式覆盖
HOST_PORT=18000 sh start.sh

# 连接到已有或自动创建的 Docker network
NETWORK_NAME=backend sh start.sh

# 指定镜像名、容器名和日志目录
IMAGE_NAME=ai-paper-api:prod CONTAINER_NAME=ai-paper-api-prod HOST_LOG_DIR=/data/ai-paper-api/logs sh start.sh

# 如需临时只启动 API 或只启动 scheduler，可显式覆盖 APP_ROLE
APP_ROLE=api ENV_FILE=.env.docker sh start.sh
APP_ROLE=scheduler ENV_FILE=.env.docker sh start.sh
```

脚本默认会把宿主机 `./logs` 挂载到容器内 `/app/logs`，与 `.env` 中默认的 `LOG_FILE=logs/app.log` 对齐。
为了避免日志目录权限不匹配，`start.sh` 默认使用当前宿主机用户的 UID/GID 启动容器；如果你希望使用镜像内置的 `app` 用户，可设置 `RUN_AS_HOST_USER=false`。

### 3. worker 与连接数

生产环境建议设置：

```env
APP_DEBUG=false
WEB_CONCURRENCY=2
```

MySQL 和 Redis 的连接上限按 worker 数放大：

```text
MySQL 理论最大连接数 = WEB_CONCURRENCY * MYSQL_POOL_MAX
Redis 理论最大连接数 = WEB_CONCURRENCY * REDIS_MAX_CONNECTIONS
```

如果还有多台机器或多个容器副本，还需要继续乘以实例数。

### 4. 定时任务与多 worker

本模板使用 APScheduler 作为进程内定时任务调度器。Uvicorn 多 worker 会启动多个独立进程，如果生产 API worker 都在 lifespan 中启动 APScheduler，同一个任务会重复执行。

因此项目采用两套启动路径：

- 开发环境：`APP_DEBUG=true` 时，`main.py` 固定只启动 1 个 worker，`app.py` 的 lifespan 会同时启动 APScheduler，方便本地调试。
- 生产环境：`APP_DEBUG=false` 时，API worker 不启动 APScheduler；定时任务由 `tasks.runner` 作为独立进程启动。

定时任务独立入口：

```bash
uv run python -m tasks.runner
```

Docker 部署默认使用一个容器托管两个进程：

```bash
# APP_DEBUG=false 时，start.sh 自动启动 API 进程和 scheduler 进程
ENV_FILE=.env.docker sh start.sh
```

容器内的启动脚本会同时启动 `python main.py` 和 `python -m tasks.runner`：API 进程可按 `WEB_CONCURRENCY` 多 worker 运行，scheduler 始终只有一个独立进程。如果任一进程退出，容器会整体退出，交给 Docker 重启策略处理。

当前默认部署方式的边界：

- 只启动一个应用容器副本时，可以使用默认的 `APP_ROLE=auto`，由 `start.sh` 在一个容器内同时托管 API 和 scheduler。
- 如果未来需要启动多个应用容器副本，不要让每个副本都运行 `APP_ROLE=all`，否则每个副本都会启动一份 scheduler，定时任务会重复执行。
- 多副本部署时，建议多个 API 容器使用 `APP_ROLE=api`，并且只保留一个 scheduler 容器使用 `APP_ROLE=scheduler`。
- 如果必须多个 scheduler 实例同时存在，需要给具体任务增加 Redis/MySQL 分布式锁，或改用外部调度系统。

## 新增业务模块流程

1. `models/` 下新建模型文件，在 `core/config.py` 的 `TORTOISE_ORM.apps.models.models` 列表里注册
2. `schemas/` 下新建对应的 Schema（请求/响应体）
3. `services/` 下新建业务逻辑实现
4. `api/v1/` 下新建路由文件
5. 在 `api/v1/__init__.py` 里 `include_router`
6. 执行 `uv run aerich migrate && uv run aerich upgrade` 同步数据库

## 关键设计决策

| 问题 | 决策 |
|------|------|
| MySQL/Redis 连接对象在哪初始化？| `core/database.py` 和 `core/redis.py` 声明，由 `app.py` lifespan 或 `tasks.runner` 统一 init/close |
| MySQL/Redis 连接失败怎么办？| 启动阶段只打印 warning 并继续运行；健康检查会返回 degraded，依赖数据库/缓存的接口在调用时再暴露具体错误 |
| 定时任务写在哪？| `tasks/scheduler.py` 写任务和注册函数；开发环境由 `app.py` 启动，生产环境由 `tasks.runner` 独立进程启动 |
| 环境变量怎么管理？| `core/config.py` 用 pydantic-settings 读取，全项目只 import `settings` 对象 |
| 接口统一响应格式？| `schemas/common.py` 的 `Response[T]` 泛型包装 |
| 数据库迁移？| aerich（Tortoise-ORM 官方迁移工具）|
