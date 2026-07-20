---
name: mysql-schema-changes
description: ai-paper-api 的 MySQL/Tortoise 数据库结构变更规范。新增、删除或修改表、字段、索引、唯一约束、外键、默认值、字符集、排序规则和注释，调整 models 或 sql/init.sql，使用 Aerich，排查实际库与代码漂移或中文乱码时必须使用。
---

# ai-paper-api MySQL 结构变更

## 开始前

1. 读取根目录 `AGENTS.md`、项目 skills 索引和编码规范；修改 Python model 时继续读取 `python-code-style` 的强制引用。
2. 执行 `rtk git status --short`，保留用户已有改动。
3. 阅读相关 `models/*.py`、`models/__init__.py`、`core/config.py` 的 `TORTOISE_ORM`、`sql/init.sql`，以及受影响的 schema、service、API 和测试。
4. 先用 `.agents/skills/mysql-schema-changes/scripts/local-mysql.sh status` 和只读查询确认目标确实是本地开发库；未确认前不得执行 DDL/DML。

## 当前项目事实

- 数据库是 MySQL，运行时 ORM 是 Tortoise-ORM；模型注册位于 `core/config.py`。
- 当前初始化来源只有 `sql/init.sql`，其中同时包含表结构和本地默认用户数据。
- 项目仍处于统一维护初始化 SQL 的阶段：当前没有 `migrations/`，不要自行创建补丁式 SQL 目录或把一次性 ALTER 文件提交进仓库。
- `pyproject.toml` 已配置 Aerich，但在项目明确切换到版本化迁移前，不要擅自初始化或混用 Aerich 与手工迁移。
- 本地库由 WSL 中的 Docker MySQL 提供，连接参数来自根目录 `.env` 的 `MYSQL_HOST`、`MYSQL_PORT`、`MYSQL_USER`、`MYSQL_PASSWORD`、`MYSQL_DB`。
- `.env` 只用于连接。不得输出、记录、提交或复制密码及其他密钥；文档和测试只能使用占位值。
- 当前库存在既有排序规则差异。变更前读取相关表和外键列的实际 charset/collation，不借普通结构变更顺手全库归一化。

## 三方一致性

每次结构变更都要检查并同步：

1. **ORM 契约**：更新 `models/*.py` 中的字段、关系、索引/唯一约束、`description` 和 `table_description`；新增模型时同步 `models/__init__.py` 与 `core/config.py` 注册。
2. **全新安装**：更新 `sql/init.sql`，使空数据库一次执行后直接得到最新结构。保持外键依赖顺序；只有业务确实要求时才修改初始化数据。
3. **本地实际库**：用一份经过审查的临时 SQL 执行精确的 ALTER/CREATE，并通过 `SHOW CREATE TABLE` 与 `information_schema` 验证。不要对已有数据的库重新执行完整 `sql/init.sql` 来代替迁移。

若字段影响请求、响应或业务规则，继续同步 schema、service、API、测试和专题文档。仅改实际数据库、不改仓库，或只改 model/初始化 SQL、不更新本地库，都不算完成。

## 变更流程

1. 用只读查询记录受影响表的字段、默认值、索引、外键、注释、行数和排序规则。
2. 明确数据兼容方案：新增非空字段的历史值、字段收窄/改名、唯一索引冲突、外键孤儿、JSON/时间语义和应用发布顺序。
3. 先修改 ORM 和 `sql/init.sql`，逐项对齐类型、null、default、长度、精度、索引、外键动作和注释。
4. 将本地库所需 DDL 写入仓库外的临时 SQL 文件；文件包含 `SET NAMES utf8mb4;`，并且只包含本次变更。
5. 在用户已授权修改本地开发库后，执行 `.agents/skills/mysql-schema-changes/scripts/local-mysql.sh apply <临时 SQL>`。MySQL DDL 可能隐式提交，不假设事务可以完整回滚。
6. 运行 `schema`、`query` 和 `verify-comments` 验证实际结构，再运行受影响的 Ruff、Mypy、pytest 和 OpenAPI 检查。

当前项目进入生产或需要多人共享增量升级时，先明确迁移策略，再启用 Aerich 或正式迁移目录；不得事后把开发库手工操作伪装成可复现迁移。

## SQL 与 Tortoise 规则

- SQL 保存为 UTF-8 无 BOM，并在连接/脚本前部使用 `SET NAMES utf8mb4;`。
- 新表使用 InnoDB 和 utf8mb4；排序规则必须显式选择，并与被引用字符串列兼容。修改现有表时优先保留其当前规则。
- 表写准确的中文 `COMMENT`；业务字段在 SQL 中写 `COMMENT`，Tortoise 字段写对应 `description`。公共技术字段 `id`、`created_at`、`updated_at` 可沿用基类语义。
- 状态字段说明主要取值；积分说明增减/余额语义；时间说明业务时点；JSON 说明内容结构；外部编号和密钥字段说明来源与用途。
- Tortoise 外键属性会生成 `<name>_id` 列；对齐实际列名、null、`ON DELETE`、索引和关系类型，不重复声明冲突字段。
- 修改 `MODIFY COLUMN` 时完整保留类型、null、default、字符集/排序规则、自动更新时间和注释，避免遗漏属性。
- 同步检查主键、唯一约束、幂等键、查询索引和外键；尤其保护用户、订单、生成任务、积分流水与模型调用日志的关联完整性。
- 初始化数据必须使用明显的本地演示值，不写生产账号、真实 API Token、模型 Key 或密码明文。修改 seed 时保持重复执行语义可控。
- `DB_GENERATE_SCHEMAS` 不能替代结构管理；生产和常规开发保持关闭。

## 破坏性与生产边界

- 用户要求设计或审查，不等于授权执行本地 DDL；只有明确要求落库时才运行 `apply`。
- `DROP DATABASE`、`DROP TABLE`、`TRUNCATE`、删列、改名、类型收窄、重建唯一约束等操作，必须先核对数据、备份/恢复方案并获得明确授权。
- 配套脚本默认拒绝常见破坏性 SQL；不得用环境开关绕过，除非用户已明确授权且目标再次确认是本地开发库。
- 永不连接或修改生产库。主机不是 loopback、本地 Docker 映射端口或用户明确确认的隔离开发环境时，停止并询问。
- 不在命令参数、日志、最终回复或 SQL 注释中暴露 `.env` 密码。

## 本地工具

从仓库根目录执行：

```bash
rtk .agents/skills/mysql-schema-changes/scripts/local-mysql.sh status
rtk .agents/skills/mysql-schema-changes/scripts/local-mysql.sh schema <table> [table...]
rtk .agents/skills/mysql-schema-changes/scripts/local-mysql.sh query "SHOW INDEX FROM <table>"
rtk .agents/skills/mysql-schema-changes/scripts/local-mysql.sh apply </tmp/change.sql>
rtk .agents/skills/mysql-schema-changes/scripts/local-mysql.sh verify-comments <table> [table...]
```

- `status` 显示数据库、MySQL 版本和连接字符集，不显示密码。
- `query` 只允许 `SELECT`、`SHOW`、`DESCRIBE/DESC`、`EXPLAIN`。
- `schema` 输出指定表的 `SHOW CREATE TABLE`。
- `apply` 只用于已审查的临时增量 SQL，不用于执行完整 `sql/init.sql`。
- `verify-comments` 要求表注释及业务字段注释非空，并忽略基类公共技术字段。

## 完成验证

- 用 `schema` 或 `information_schema` 对比 ORM、`sql/init.sql` 与实际库的类型、默认值、索引、外键、注释和排序规则。
- 对新增/修改的 model 运行 `rtk uv run ruff check <paths>` 和 `rtk uv run mypy <paths>`。
- 运行直接覆盖受影响业务的 pytest；API/schema 变化时加跑 OpenAPI 生成检查。
- 运行 `rtk git diff --check`，确认未提交临时 SQL、数据库 dump、`.env` 或凭据。
- 最终报告仓库改动、本地库是否实际执行、验证结果、数据兼容处理和未执行的生产操作；不得报告密码或密钥。
