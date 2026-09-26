"""从现有业务库增量升级；已存在对象跳过，允许 DDL 部分失败后重试。"""

from migrations.runner import MigrationDB, MigrationError


# 检查迁移基线后返回版本固定的 SQL
async def upgrade(db: MigrationDB) -> str:
    """检查 db 的基础表；返回增量 SQL，不导入含演示数据的初始化脚本。"""
    rows = await db.execute_query_dict(
        "SELECT TABLE_NAME AS name FROM information_schema.tables WHERE table_schema = DATABASE()"
    )
    if not set(["paper_orders","paper_generation_tasks"]).issubset({str(row["name"]) for row in rows}):
        raise MigrationError("缺少基础业务表；空库请先按 sql/init.sql 初始化，旧库请核对适用基线")
    return r"""
SET NAMES utf8mb4;

SET @ddl = IF(
  EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = DATABASE() AND table_name = 'paper_orders' AND column_name = 'document_type'),
  'SELECT 1',
  'ALTER TABLE `paper_orders` ADD COLUMN `document_type` VARCHAR(32) NOT NULL DEFAULT ''thesis'' COMMENT ''文档类型'''
);
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @ddl = IF(
  EXISTS (SELECT 1 FROM information_schema.statistics WHERE table_schema = DATABASE() AND table_name = 'paper_orders' AND index_name = 'idx_paper_orders_user_type_time'),
  'SELECT 1',
  'ALTER TABLE `paper_orders` ADD KEY `idx_paper_orders_user_type_time` (`user_id`, `document_type`, `created_at`)'
);
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @ddl = IF(
  EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = DATABASE() AND table_name = 'paper_generation_tasks' AND column_name = 'document_type'),
  'SELECT 1',
  'ALTER TABLE `paper_generation_tasks` ADD COLUMN `document_type` VARCHAR(32) NOT NULL DEFAULT ''thesis'' COMMENT ''文档类型'''
);
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @ddl = IF(
  EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = DATABASE() AND table_name = 'paper_generation_tasks' AND column_name = 'result_data'),
  'SELECT 1',
  'ALTER TABLE `paper_generation_tasks` ADD COLUMN `result_data` JSON NULL COMMENT ''结构化文档生成结果'''
);
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @ddl = IF(
  EXISTS (SELECT 1 FROM information_schema.statistics WHERE table_schema = DATABASE() AND table_name = 'paper_generation_tasks' AND index_name = 'idx_paper_generation_tasks_type_status'),
  'SELECT 1',
  'ALTER TABLE `paper_generation_tasks` ADD KEY `idx_paper_generation_tasks_type_status` (`document_type`, `status`, `updated_at`)'
);
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;
"""
