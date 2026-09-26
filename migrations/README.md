# AI Paper 版本化数据库迁移

参考 FleetOps 的 runner 模式。版本文件为 `models/<递增序号>_<日期>_<说明>.py`，
提供 `async upgrade(db) -> str`，返回 SQL，也可通过 db 执行参数化数据更新。
不再维护手工执行的 sql/migrations 目录。

## 当前版本

- 001：论文订单/任务增加 document_type、任务 result_data 及相关索引（适用已有 paper_orders、paper_generation_tasks 的库）。
- 002：论文材料订单/任务表，以及 point_ledgers/model_call_logs 的关联列、索引、外键（依赖 users、point_ledgers、model_call_logs，MySQL 8.0）。

现有两份人工 SQL 的更新内容已完整迁入上述 Python 文件，不删除、清空或回填业务数据。
空库先执行 sql/init.sql；不能对已有库重跑初始化脚本。旧 writing_* 表不在本批自动重命名或搬迁范围。

## 执行与失败处理

start.sh 使用待部署镜像，在替换应用容器前自动执行预检和迁移；文件预检不连接数据库。
只构建依赖镜像不执行迁移。直接 docker run 或本地 main.py 不自动执行，请显式运行
`uv run python -m migrations.runner`。不混用 Aerich。

同一物理 MySQL 会话持有按库区分的 GET_LOCK，串行执行 SQL 并登记 schema_migration。
所有多语句结果集均须读取，后续语句失败也阻止登记。失败退出码为 1，部署停止。
连接关闭会释放锁；执行中不自动重连。数据库账本由执行器管理，不作为业务 ORM 模型注册；
其结构同时保留在 sql/init.sql 供全新初始化使用。

已执行文件禁止修改、改名或在历史序号中插入新版本。新增变更只能追加更大序号。
所有迁移在执行前预加载语法与入口，再校验全部历史 checksum。成功才写账本，
已执行版本跳过。数据库历史账本即使对应文件归档也需保留。

MySQL DDL 隐式提交：失败可能留下部分结构，不能依赖事务回滚。
迁移必须可重入，数据回填需带条件/去重，不能盲目重放累加、扣费等非幂等操作。
先备份并在隔离库演练。当前两版按对象是否存在跳过，不负责识别或修正同名对象的结构漂移。
旧服务在迁移期间可能仍运行；本批仅增加结构，未来破坏性迁移必须安排维护窗口与恢复方案。
