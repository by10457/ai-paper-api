# FastAPI 模板项目初始化提示词

你是一个资深 Python/FastAPI 编程助手。请帮助我把当前 FastAPI 模板项目初始化成一个真实业务项目。

开始前请先阅读项目根目录下的 `README.md`、`.env.example`、`pyproject.toml`、`Dockerfile`、`start.sh`、`core/config.py`，理解模板已有约定后再操作。不要直接套用通用脚本。

## 工作模式

请严格按以下流程执行：

1. 先检查当前工作区状态，识别是否已有未提交或非本次任务产生的改动。
2. 先向我询问初始化所需信息，等我回答完整后再修改文件。
3. 如果我的回答有遗漏、不合法或互相冲突，继续追问，不要猜。
4. 只修改模板初始化必需的文件，不做无关重构。
5. 不要提交 git commit，不要删除我已有的业务代码。
6. 完成后汇总修改了哪些文件、执行了哪些命令、还有哪些需要我手动确认。

## 需要先询问我的问题

请一次性询问以下问题，并给出推荐默认值：

1. 项目名称需要改成什么？
   - 需要同时询问 Python 包项目名和应用展示名。
   - Python 包项目名用于 `pyproject.toml` 的 `[project].name`，建议使用小写、短横线格式，例如 `ai-paper-api`。
   - 应用展示名用于环境变量 `APP_NAME`，例如 `AI Paper API`。
   - 需要询问 Docker 镜像名和容器名前缀是否跟随项目名同步修改。
   - Docker 镜像名用于 `start.sh` 的 `IMAGE_NAME` 默认值，例如 `ai-paper-api:latest`。
   - Docker 容器名前缀用于 `start.sh` 的 `CONTAINER_NAME` 默认值，例如 `ai-paper-api` 和 `ai-paper-api-scheduler`。
2. 是否启动定时任务调度器？
   - 对应 `.env` 和 `.env.docker` 的 `SCHEDULER_ENABLED`。
   - 如果只是普通 API 项目，推荐 `false`；如果需要 APScheduler 定时任务，选择 `true`。
3. 项目启动端口是什么？
   - 对应 `APP_PORT`。
   - 需要询问是否同步修改 `Dockerfile` 里的 `APP_PORT` 默认值、`EXPOSE` 端口和健康检查默认端口。
   - 需要询问是否同步修改 `start.sh` 里的端口 fallback、帮助文案和示例命令。
4. JWT 密钥怎么处理？
   - 询问是由我提供密钥，还是由你生成。
   - 如果由你生成，询问生成多少 bit，推荐 `256 bit`。
   - 生成后写入 `.env` 和 `.env.docker` 的 `SECRET_KEY`，不要写入 `.env.example` 的真实密钥。
5. MySQL 密码是什么？
   - 对应 `MYSQL_PASSWORD`。
6. MySQL 连接的数据库名称是什么？
   - 对应 `MYSQL_DB`。
   - 同时询问是否需要更新 `sql/init.sql` 中示例数据库名。
7. Redis 密码是什么？
   - 对应 `REDIS_PASSWORD`。
   - 如果 Redis 没有密码，允许留空。
8. MySQL 和 Redis 的连接地址是什么？
   - 本机直接运行通常是 `127.0.0.1`。
   - Docker 应用连接宿主机服务通常是 `host.docker.internal`。
   - Docker Compose 或同一 Docker network 内通常填写服务名，例如 `mysql`、`redis`。
   - 需要分别询问 `.env` 和 `.env.docker` 是否使用不同 host。
9. 是否需要安装额外依赖包？
   - 如果需要，请询问依赖名称和是否为开发依赖。
   - 普通依赖使用 `uv add <package>`。
   - 开发依赖使用 `uv add --dev <package>`。

## 修改要求

根据我的回答执行以下操作：

先按下面的文件清单建立修改计划，不要遗漏受影响文件：

| 文件 | 何时需要修改 | 重点检查项 |
| --- | --- | --- |
| `pyproject.toml` | 修改 Python 包项目名或依赖 | `[project].name`、依赖列表 |
| `uv.lock` | 修改项目名或依赖后 | 锁文件中的项目名和依赖版本 |
| `.env` | 每次初始化都需要生成或更新 | 本地开发环境变量 |
| `.env.docker` | 每次初始化都需要生成或更新 | Docker/生产环境变量 |
| `Dockerfile` | 同步 Docker 默认端口时 | `ENV APP_PORT`、`EXPOSE`、`HEALTHCHECK` 默认端口 |
| `start.sh` | 同步 Docker 命名或默认端口时 | `IMAGE_NAME`、默认 `CONTAINER_NAME`、scheduler 容器名、端口 fallback、帮助文案、示例命令、临时文件名前缀 |
| `README.md` | 我确认同步文档时 | 项目名、端口、启动命令示例 |
| `public/index.html` | 我确认同步静态演示页展示名时 | 页面标题、首屏标题、演示文案中的旧模板名 |
| `sql/init.sql` | 我确认同步数据库示例名时 | 示例数据库名 |

1. 项目名称
   - 修改 `pyproject.toml` 的 `[project].name`。
   - 如果我要求同步修改展示名，更新 `.env`、`.env.docker` 中的 `APP_NAME`。
   - 如果我确认同步 Docker 命名，更新 `start.sh`：
     - `IMAGE_NAME` 默认值。
     - API 容器默认 `CONTAINER_NAME`。
     - scheduler 容器默认 `CONTAINER_NAME`。
     - `usage()` 帮助文案里的默认镜像名、容器名和示例命令。
     - `sanitize_env_file()` 使用的临时文件名前缀，避免继续使用旧模板名。
   - 如果 README 或静态演示页里仍有明显的旧模板名，并且我同意同步替换，则做小范围替换。
   - 修改完成后搜索旧模板名，例如 `t-fastapi`、`T-FastAPI`、`T-FastApi`。如果仍有残留，逐项判断是否需要替换，并在结果里说明保留原因。

2. uv 初始化和依赖
   - 如果项目已经有 `pyproject.toml`，不要重新执行会覆盖配置的 `uv init`。
   - 修改项目名或依赖后，执行 `uv lock` 或 `uv sync`，让 `uv.lock` 与 `pyproject.toml` 保持一致。
   - 如果我提供了额外依赖，按普通依赖或开发依赖分别用 `uv add` / `uv add --dev` 安装。

3. 环境变量文件
   - 基于 `.env.example` 生成或更新 `.env` 和 `.env.docker`。
   - 保留 `.env.example` 作为模板文件，除非我明确要求修改示例默认值。
   - 写入这些关键项：
     - `APP_NAME`
     - `APP_ENV`
     - `APP_DEBUG`
     - `APP_HOST`
     - `APP_PORT`
     - `SCHEDULER_ENABLED`
     - `SECRET_KEY`
     - `MYSQL_HOST`
     - `MYSQL_PORT`
     - `MYSQL_USER`
     - `MYSQL_PASSWORD`
     - `MYSQL_DB`
     - `REDIS_HOST`
     - `REDIS_PORT`
     - `REDIS_PASSWORD`
     - `REDIS_DB`
   - `.env` 推荐用于本地开发：`APP_ENV=development`、`APP_DEBUG=true`。
   - `.env.docker` 推荐用于 Docker/生产：`APP_ENV=production`、`APP_DEBUG=false`。

4. 定时任务
   - 按我的选择设置 `SCHEDULER_ENABLED=true` 或 `false`。
   - 不要删除 `tasks/` 代码。
   - 如果 `SCHEDULER_ENABLED=false`，说明 Docker 默认 `APP_ROLE=auto` 会只启动 API。

5. 端口
   - 修改 `.env` 和 `.env.docker` 的 `APP_PORT`。
   - 如果我确认同步 Docker 默认端口，则修改 `Dockerfile` 中的 `APP_PORT`、`EXPOSE` 和健康检查默认端口。
   - 如果我确认同步启动脚本默认端口，则修改 `start.sh`：
     - `HOST_PORT` 说明里的 fallback 端口。
     - `CONTAINER_PORT` 说明里的 fallback 端口。
     - 读取 `APP_PORT` 后使用的默认端口 fallback。
     - 示例命令中的端口值，如有旧端口或不合适的示例端口，需要同步调整。
   - 如发现 `README.md` 中有旧端口示例，询问我是否同步更新文档。
   - 修改完成后搜索旧端口，例如 `10457`。如果仍有残留，逐项判断是否需要替换，并在结果里说明保留原因。

6. JWT 密钥
   - 如果需要生成密钥，使用安全随机源生成。
   - 推荐方式之一：
     ```bash
     python - <<'PY'
     import secrets
     print(secrets.token_hex(32))
     PY
     ```
     这会生成 256 bit 随机值，并以 64 个十六进制字符展示。
   - 不要把真实密钥写入 README。

7. MySQL / Redis
   - 按我的回答设置 `.env` 和 `.env.docker`。
   - 如果 Docker 环境连接宿主机 MySQL/Redis，使用 `host.docker.internal`。
   - 如果连接同一 Docker network 中的服务，使用服务名或容器名。

## 验证要求

修改完成后请执行合适的验证：

1. `uv sync`
2. `uv run pytest tests/ -v`
3. 如修改了 Dockerfile 或 Docker 配置，至少做语法和关键配置检查；只有我要求时再构建镜像。
4. 检查 `.env`、`.env.docker` 是否存在，且关键变量已按我的回答写入。
5. 检查 `pyproject.toml` 和 `uv.lock` 中项目名是否一致。
6. 检查 `Dockerfile`、`start.sh`、`README.md`、`public/index.html` 中是否还残留旧模板名或旧端口；残留项必须说明是否有意保留。

如果某个命令失败，请先根据错误信息修复；如果失败原因是外部服务未启动，例如 MySQL/Redis 不可用，要明确说明，而不是掩盖失败。

## 输出格式

完成后请按以下格式回复：

```text
完成情况：
- 已修改：...
- 已生成：...
- 已执行：...

验证结果：
- uv sync：通过/失败，原因...
- pytest：通过/失败，原因...

注意事项：
- ...
```
