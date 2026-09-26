"""从现有业务库增量升级；已存在对象跳过，允许 DDL 部分失败后重试。"""

from migrations.runner import MigrationDB, MigrationError


# 检查迁移基线后返回版本固定的 SQL
async def upgrade(db: MigrationDB) -> str:
    """检查 db 的基础表；返回增量 SQL，不导入含演示数据的初始化脚本。"""
    rows = await db.execute_query_dict(
        "SELECT TABLE_NAME AS name FROM information_schema.tables WHERE table_schema = DATABASE()"
    )
    if not set(["users","point_ledgers","model_call_logs"]).issubset({str(row["name"]) for row in rows}):
        raise MigrationError("缺少基础业务表；空库请先按 sql/init.sql 初始化，旧库请核对适用基线")
    return r"""
SET NAMES utf8mb4;

CREATE TABLE IF NOT EXISTS `paper_material_orders` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `created_at` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  `updated_at` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  `order_sn` VARCHAR(64) NOT NULL COMMENT '论文材料订单号',
  `document_type` VARCHAR(32) NOT NULL COMMENT '文档类型：proposal_report/literature_review/task_book',
  `idempotency_key` VARCHAR(128) NULL COMMENT '请求幂等键',
  `title` VARCHAR(200) NOT NULL COMMENT '文档标题',
  `request_payload` JSON NOT NULL COMMENT '生成请求快照',
  `cost_points` INT NOT NULL DEFAULT 20 COMMENT '应扣积分',
  `paid_points` INT NOT NULL DEFAULT 0 COMMENT '已扣积分',
  `refunded_points` INT NOT NULL DEFAULT 0 COMMENT '已退积分',
  `status` VARCHAR(32) NOT NULL DEFAULT 'paid' COMMENT '订单状态',
  `task_id` VARCHAR(64) NULL COMMENT '当前生成任务 ID',
  `storage_provider` VARCHAR(32) NULL COMMENT '主存储类型',
  `file_key` VARCHAR(512) NULL COMMENT '主存储文件 key',
  `local_file_key` VARCHAR(512) NULL COMMENT '本地兜底文件 key',
  `download_url` VARCHAR(1024) NULL COMMENT '下载链接',
  `callback_url` VARCHAR(1024) NULL COMMENT '生成完成回调地址',
  `callback_secret` VARCHAR(255) NULL COMMENT '生成完成回调密钥',
  `last_error` VARCHAR(500) NULL COMMENT '最近一次错误',
  `paid_at` DATETIME(6) NULL COMMENT '扣费时间',
  `refunded_at` DATETIME(6) NULL COMMENT '退积分时间',
  `started_at` DATETIME(6) NULL COMMENT '开始生成时间',
  `completed_at` DATETIME(6) NULL COMMENT '完成时间',
  `retry_count` INT NOT NULL DEFAULT 0 COMMENT '自动重试次数',
  `next_retry_at` DATETIME(6) NULL COMMENT '下次自动重试时间',
  `user_id` INT NOT NULL COMMENT '用户',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uid_paper_material_orders_order_sn` (`order_sn`),
  UNIQUE KEY `uid_paper_material_orders_user_id_idempotency_key` (`user_id`, `idempotency_key`),
  KEY `idx_paper_material_orders_user_id` (`user_id`),
  KEY `idx_paper_material_orders_user_type_time` (`user_id`, `document_type`, `created_at`),
  KEY `idx_paper_material_orders_status_next_retry_at` (`status`, `next_retry_at`),
  CONSTRAINT `fk_paper_material_orders_user_id` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='论文材料订单';

CREATE TABLE IF NOT EXISTS `paper_material_generation_tasks` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `created_at` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  `updated_at` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  `idempotency_key` VARCHAR(128) NULL COMMENT '请求幂等键',
  `task_id` VARCHAR(64) NOT NULL COMMENT '生成任务 ID',
  `document_type` VARCHAR(32) NOT NULL COMMENT '文档类型：proposal_report/literature_review/task_book',
  `title` VARCHAR(200) NOT NULL COMMENT '文档标题',
  `status` VARCHAR(32) NOT NULL DEFAULT 'paid' COMMENT '任务状态',
  `current_stage` VARCHAR(64) NULL COMMENT '当前生成阶段',
  `progress` INT NOT NULL DEFAULT 0 COMMENT '当前生成进度',
  `process_events` JSON NULL COMMENT '生成过程事件',
  `process_metadata` JSON NULL COMMENT '生成过程关键数据',
  `result_data` JSON NULL COMMENT '结构化文档生成结果',
  `storage_provider` VARCHAR(32) NULL COMMENT '主存储类型',
  `file_key` VARCHAR(512) NULL COMMENT '主存储文件 key',
  `local_file_key` VARCHAR(512) NULL COMMENT '本地兜底文件 key',
  `last_error` VARCHAR(500) NULL COMMENT '最近一次错误',
  `started_at` DATETIME(6) NULL COMMENT '开始生成时间',
  `completed_at` DATETIME(6) NULL COMMENT '完成时间',
  `retry_count` INT NOT NULL DEFAULT 0 COMMENT '自动重试次数',
  `next_retry_at` DATETIME(6) NULL COMMENT '下次自动重试时间',
  `user_id` INT NOT NULL COMMENT '用户',
  `order_id` INT NOT NULL COMMENT '关联论文材料订单',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uid_paper_material_generation_tasks_task_id` (`task_id`),
  UNIQUE KEY `uid_paper_material_generation_tasks_user_id_idempotency_key` (`user_id`, `idempotency_key`),
  KEY `idx_paper_material_generation_tasks_user_id` (`user_id`),
  KEY `idx_paper_material_generation_tasks_order_id` (`order_id`),
  KEY `idx_paper_material_generation_tasks_status_next_retry_at` (`status`, `next_retry_at`),
  KEY `idx_paper_material_generation_tasks_type_status` (`document_type`, `status`, `updated_at`),
  CONSTRAINT `fk_paper_material_generation_tasks_user_id` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_paper_material_generation_tasks_order_id` FOREIGN KEY (`order_id`) REFERENCES `paper_material_orders` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='论文材料生成任务';

SET @ddl = IF(
  EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = DATABASE() AND table_name = 'point_ledgers' AND column_name = 'paper_material_order_id'),
  'SELECT 1',
  'ALTER TABLE `point_ledgers` ADD COLUMN `paper_material_order_id` INT NULL COMMENT ''关联论文材料订单'''
);
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @ddl = IF(
  EXISTS (SELECT 1 FROM information_schema.statistics WHERE table_schema = DATABASE() AND table_name = 'point_ledgers' AND index_name = 'idx_point_ledgers_paper_material_order_id'),
  'SELECT 1',
  'ALTER TABLE `point_ledgers` ADD KEY `idx_point_ledgers_paper_material_order_id` (`paper_material_order_id`)'
);
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @ddl = IF(
  EXISTS (SELECT 1 FROM information_schema.table_constraints WHERE table_schema = DATABASE() AND table_name = 'point_ledgers' AND constraint_name = 'fk_point_ledgers_paper_material_order_id' AND constraint_type = 'FOREIGN KEY'),
  'SELECT 1',
  'ALTER TABLE `point_ledgers` ADD CONSTRAINT `fk_point_ledgers_paper_material_order_id` FOREIGN KEY (`paper_material_order_id`) REFERENCES `paper_material_orders` (`id`) ON DELETE SET NULL'
);
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @ddl = IF(
  EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = DATABASE() AND table_name = 'model_call_logs' AND column_name = 'paper_material_order_id'),
  'SELECT 1',
  'ALTER TABLE `model_call_logs` ADD COLUMN `paper_material_order_id` INT NULL COMMENT ''论文材料订单'''
);
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @ddl = IF(
  EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = DATABASE() AND table_name = 'model_call_logs' AND column_name = 'paper_material_generation_task_id'),
  'SELECT 1',
  'ALTER TABLE `model_call_logs` ADD COLUMN `paper_material_generation_task_id` INT NULL COMMENT ''论文材料生成任务'''
);
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @ddl = IF(
  EXISTS (SELECT 1 FROM information_schema.statistics WHERE table_schema = DATABASE() AND table_name = 'model_call_logs' AND index_name = 'idx_model_call_logs_paper_material_order_id'),
  'SELECT 1',
  'ALTER TABLE `model_call_logs` ADD KEY `idx_model_call_logs_paper_material_order_id` (`paper_material_order_id`)'
);
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @ddl = IF(
  EXISTS (SELECT 1 FROM information_schema.statistics WHERE table_schema = DATABASE() AND table_name = 'model_call_logs' AND index_name = 'idx_model_call_logs_paper_material_generation_task_id'),
  'SELECT 1',
  'ALTER TABLE `model_call_logs` ADD KEY `idx_model_call_logs_paper_material_generation_task_id` (`paper_material_generation_task_id`)'
);
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @ddl = IF(
  EXISTS (SELECT 1 FROM information_schema.table_constraints WHERE table_schema = DATABASE() AND table_name = 'model_call_logs' AND constraint_name = 'fk_model_call_logs_paper_material_order_id' AND constraint_type = 'FOREIGN KEY'),
  'SELECT 1',
  'ALTER TABLE `model_call_logs` ADD CONSTRAINT `fk_model_call_logs_paper_material_order_id` FOREIGN KEY (`paper_material_order_id`) REFERENCES `paper_material_orders` (`id`) ON DELETE SET NULL'
);
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @ddl = IF(
  EXISTS (SELECT 1 FROM information_schema.table_constraints WHERE table_schema = DATABASE() AND table_name = 'model_call_logs' AND constraint_name = 'fk_model_call_logs_paper_material_generation_task_id' AND constraint_type = 'FOREIGN KEY'),
  'SELECT 1',
  'ALTER TABLE `model_call_logs` ADD CONSTRAINT `fk_model_call_logs_paper_material_generation_task_id` FOREIGN KEY (`paper_material_generation_task_id`) REFERENCES `paper_material_generation_tasks` (`id`) ON DELETE SET NULL'
);
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;
"""
