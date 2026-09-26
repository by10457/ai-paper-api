# 启动与部署

本文说明 AI Paper API 的本地启动、Docker 部署、进程角色和关键环境变量。

## 运行依赖

基础依赖：

- Python 3.13
- MySQL
- Redis
- uv

论文生成额外依赖：

- Chromium 或 Chrome：供 Mermaid CLI 通过 Puppeteer 渲染图。
- Mermaid CLI `mmdc`：渲染 Mermaid 图。
- 中文字体：供 matplotlib 图表和 Word 文档中文显示。

Docker 镜像已经内置 Chromium、`mmdc` 和常用中文字体；本机直接运行时需要自行安装。

## 本地启动

```bash
cp .env.example .env
uv sync
mysql -u root -p < sql/init.sql
uv run python main.py
```

推荐本地配置：

```env
APP_ENV=development
APP_DEBUG=true
APP_RELOAD=false
APP_HOST=0.0.0.0
APP_PORT=10462
SCHEDULER_ENABLED=true
MYSQL_HOST=127.0.0.1
REDIS_HOST=127.0.0.1
```

本地启动后访问：

- `http://localhost:10462/docs`
- `http://localhost:10462/api/v1/health`
- `http://localhost:10462/index.html`

## 生产 Docker 部署

生产推荐使用 `.env.docker`：

```bash
ENV_FILE=.env.docker sh start.sh
```

常用构建模式：

| 命令 | 说明 |
| --- | --- |
| `ENV_FILE=.env.docker sh start.sh` | 常规部署，复用 runtime-base，只重建业务代码层。 |
| `BUILD_MODE=deps ENV_FILE=.env.docker sh start.sh` | 只重建 runtime-base，依赖或系统软件变化时使用。 |
| `BUILD_MODE=full ENV_FILE=.env.docker sh start.sh` | 完整构建所有阶段，排查缓存问题时使用。 |
| `BUILD_MODE=none ENV_FILE=.env.docker sh start.sh` | 不构建，直接用已有镜像重建容器。 |

`start.sh` 默认使用：

- `BUILD_MODE=fast`
- `DOCKER_BUILDKIT=1`
- 腾讯 Debian apt 镜像
- 腾讯 PyPI 镜像
- npmmirror npm 镜像

`Dockerfile` 不直接执行 `uv sync --frozen` 安装依赖，而是先从 `uv.lock` 导出锁定版本的 requirements，再通过国内镜像源安装，避免服务器访问 `files.pythonhosted.org` 卡住。

## 数据库自动增量升级

`start.sh` 在构建后、发布前端和替换应用容器前，用待部署镜像执行迁移文件预检、数据库只读连接检查，再自动应用未执行版本。与应用使用相同的环境文件、Docker 网络和 host-gateway；`fast/full/none` 部署均执行，`deps` 只构建依赖，不运行迁移。API worker 和 scheduler 不重复执行迁移。

迁移放在 `migrations/models/`，规范见 [迁移说明](../migrations/README.md)。数据库 `schema_migration` 保存版本、校验和、完成时间。失败返回非零退出码并停止部署，旧容器尚未替换；数据库 DDL 可能已部分生效，不能认为停止部署等于回滚数据库。先备份、确认兼容基线和维护窗口。多副本部署需自行协调旧 worker 停止写入，迁移锁只保护迁移器。

全新数据库仍先执行 `sql/init.sql`，迁移器不会自动导入演示用户。已初始化到最新结构的库会跳过已存在对象并登记版本。既有同名对象不会自动修正结构漂移，上线前需对照初始化结构检查。部署账号需要执行对应 CREATE/ALTER/INDEX/外键及账本读写权限。

本地可执行：

```bash
uv run python -m migrations.runner --check     # 不连接数据库
uv run python -m migrations.runner --preflight # 只读连通性检查
uv run python -m migrations.runner             # 实际升级本地目标库
```

## 进程角色

`APP_ROLE` 支持：

| 角色 | 说明 |
| --- | --- |
| `auto` | 默认值。开发环境只启动 API；生产环境启动 API + scheduler。 |
| `all` | 同一个容器内启动 API 和 scheduler/worker。 |
| `api` | 只启动 API。 |
| `scheduler` | 只启动定时任务和论文生成 worker。 |

生产单容器部署：

```env
APP_DEBUG=false
APP_ROLE=auto
WEB_CONCURRENCY=4
SCHEDULER_ENABLED=true
```

多容器或多副本部署：

- API 容器设置 `APP_ROLE=api`。
- 只保留一个 scheduler 容器设置 `APP_ROLE=scheduler`。
- 不要让多个容器同时使用 `APP_ROLE=all`，否则定时任务和论文生成 worker 会重复运行。

## worker 与连接池

生产 4 个 API worker + 1 个 scheduler/worker 进程时，连接上限大致为：

```text
MySQL 最大连接数 ≈ 5 * MYSQL_POOL_MAX
Redis 最大连接数 ≈ 5 * REDIS_MAX_CONNECTIONS
```

如果再增加容器副本，需要继续乘以实例数。

参考配置：

```env
WEB_CONCURRENCY=4
MYSQL_POOL_MIN=5
MYSQL_POOL_MAX=20
REDIS_MAX_CONNECTIONS=50
```

论文生成整篇任务并发由 scheduler/worker 进程读取：

```env
PAPER_GENERATION_CONCURRENCY=30
```

如果只启动一个 scheduler/worker 进程，该值就是全局整篇论文并发上限。

## public 目录挂载

生产推荐把宿主机目录挂载到容器：

```env
HOST_PUBLIC_DIR=/data/server/ai-paper-api/public
CONTAINER_PUBLIC_DIR=/app/public
```

作用：

- 前端静态文件可以直接放在宿主机 `public` 目录中更新。
- 本地兜底论文产物 `public/output/thesis` 在容器重建后保留。

部署脚本会自动创建：

```text
public/output/thesis
```

## MySQL 和 Redis 连接

如果 MySQL / Redis 安装在宿主机：

```env
MYSQL_HOST=host.docker.internal
REDIS_HOST=host.docker.internal
```

`start.sh` 默认添加 `host.docker.internal -> host-gateway`。

如果 MySQL / Redis 也是 Docker 容器：

```env
NETWORK_NAME=backend
MYSQL_HOST=mysql
REDIS_HOST=redis
```

## 常用排查命令

```bash
docker ps
docker logs -f ai-paper-api
docker exec -it ai-paper-api sh
curl http://127.0.0.1:10462/api/v1/health
```

查看 Redis 队列：

```bash
redis-cli -n <db> LLEN ai-paper:queue:paper:ready
redis-cli -n <db> ZCARD ai-paper:queue:paper:delayed
redis-cli -n <db> SMEMBERS ai-paper:queue:paper:enqueued
```

## 生产配置检查清单

- `APP_DEBUG=false`
- `SECRET_KEY` 已替换为高强度随机值
- `WEB_CONCURRENCY` 与 MySQL/Redis 连接池匹配
- `PAPER_CALLBACK_SECRET` 与上游业务系统一致
- `PUBLIC_BASE_URL` 是公网可访问地址
- `STORAGE_PROVIDER` 和对应对象存储配置完整
- 管理后台已经配置 `outline`、`fulltext`、`figure` 或 `default` 模型
- Redis 可连接，论文 worker 日志显示已启动
