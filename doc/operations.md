# 运维与排查

本文记录常见运维检查、队列排查、生成失败处理和配置同步注意事项。

## 健康检查

```bash
curl http://127.0.0.1:10462/api/v1/health
```

Docker：

```bash
docker ps
docker logs -f ai-paper-api
docker inspect ai-paper-api --format '{{json .State.Health}}'
```

## 日志

默认日志文件：

```env
LOG_FILE=logs/app.log
```

Docker 生产建议挂载：

```env
HOST_LOG_DIR=/data/server/ai-paper-api/logs
CONTAINER_LOG_DIR=/app/logs
```

## Redis 队列排查

```bash
redis-cli -h <host> -p <port> -n <db> LLEN ai-paper:queue:paper:ready
redis-cli -h <host> -p <port> -n <db> ZCARD ai-paper:queue:paper:delayed
redis-cli -h <host> -p <port> -n <db> SCARD ai-paper:queue:paper:enqueued
```

如果任务长时间不执行：

1. 确认 Redis 可连接。
2. 确认 scheduler/worker 进程已启动。
3. 查看 `PAPER_GENERATION_CONCURRENCY` 是否被占满。
4. 查看 `paper_generation_tasks` 是否处于 `paid` 或 `generating`。
5. 查看 `paper_orders.next_retry_at` 是否还没到重试时间。

## MySQL 排查

常见表：

| 表 | 作用 |
| --- | --- |
| `users` | 用户和积分余额。 |
| `point_ledgers` | 积分流水。 |
| `paper_outline_records` | 用户生成的大纲记录。 |
| `paper_orders` | 论文订单。 |
| `paper_generation_tasks` | 生成过程任务。 |
| `model_configs` | 模型配置。 |
| `model_call_logs` | 模型调用日志。 |
| `audit_logs` | 管理员操作审计。 |

检查待生成任务：

```sql
SELECT id, task_id, order_sn, status, current_stage, progress, next_retry_at
FROM paper_generation_tasks
ORDER BY id DESC
LIMIT 20;
```

检查订单：

```sql
SELECT id, order_sn, status, task_id, paid_points, refunded_points, last_error
FROM paper_orders
ORDER BY id DESC
LIMIT 20;
```

## 模型错误

### 第三方额度不足

表现：

```text
insufficient_user_quota
额度不足
```

系统行为：

- 用户端展示业务化错误。
- 订单失败并退积分。
- 完整错误只保留在服务端日志或模型调用日志中。

### 模型协议配置错误

表现：

```text
Authentication Fails
invalid api key
unauthorized
```

处理：

- 检查管理后台模型配置。
- 确认 `provider` 与模型协议匹配。
- 确认 `api_base_url`、`api_key`、`model_name` 正确。

## Mermaid / Chromium 问题

如果日志出现：

```text
Mermaid 渲染失败
No diagram type detected
Parse error
```

系统会尝试转 AI 插图兜底。

如果大量 Mermaid 失败：

1. 检查正文提示词是否要求输出合法 Mermaid。
2. 检查 `mmdc --version`。
3. 检查 `PUPPETEER_EXECUTABLE_PATH`。
4. 检查容器中 Chromium 是否可执行。
5. 适当降低 `MERMAID_RENDER_CONCURRENCY`。

Docker 镜像已经安装 Chromium 和 Mermaid CLI。

## 存储问题

远端存储失败不会导致论文失败。系统会降级本地下载链接。

排查：

- `STORAGE_PROVIDER` 是否正确。
- 对应 provider 的密钥和 bucket 是否完整。
- `PUBLIC_BASE_URL` 是否可访问。
- `HOST_PUBLIC_DIR` 是否正确挂载。
- `public/output/thesis` 是否存在生成文件。

## 回调问题

回调失败日志：

```text
回调业务系统最终失败
```

排查：

- `PAPER_CALLBACK_URL` 是否可从容器访问。
- Docker 内访问宿主机服务是否使用 `host.docker.internal`。
- `PAPER_CALLBACK_SECRET` 是否与上游一致。
- 上游接口是否返回 2xx。

回调失败不会影响论文完成状态。

## 数据库和 init.sql 同步

当前项目处于初始开发阶段，统一维护：

```text
sql/init.sql
```

要求：

- 不新增补丁式 SQL 文件。
- ORM 模型字段变化后，同步修改 `sql/init.sql`。
- 已连接的实际数据库也需要同步字段、索引和注释。

常见同步检查：

```sql
SHOW CREATE TABLE paper_orders;
SHOW CREATE TABLE paper_generation_tasks;
SHOW CREATE TABLE model_configs;
```

## 并发配置建议

56 核 64G 单机、4 个 API worker、1 个 scheduler/worker 的生产参考：

```env
WEB_CONCURRENCY=4
MYSQL_POOL_MIN=5
MYSQL_POOL_MAX=20
REDIS_MAX_CONNECTIONS=50
PAPER_GENERATION_CONCURRENCY=30
TEXT_LONG_CONCURRENCY=24
TEXT_SHORT_CONCURRENCY=48
MERMAID_RENDER_CONCURRENCY=8
CHART_RENDER_CONCURRENCY=12
AI_IMAGE_RENDER_CONCURRENCY=10
IMAGE_MODEL_CONCURRENCY=10
SERPAPI_CONCURRENCY=20
CROSSREF_CONCURRENCY=10
WFDATA_CONCURRENCY=20
```

调参原则：

- 上游模型 429 或超时增多，降低模型并发。
- CPU 或内存压力高，降低 Mermaid/chart 并发。
- Redis/MySQL 连接数接近上限，降低 worker 数或连接池。
- 用户等待时间过长且资源充足，再逐步提高整篇论文并发。
