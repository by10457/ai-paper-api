-- AI Paper user points and paper order schema.
-- Run this against MYSQL_DB when DB_GENERATE_SCHEMAS=false and aerich migrations are not in use.

DROP PROCEDURE IF EXISTS add_column_if_not_exists;
DELIMITER //
CREATE PROCEDURE add_column_if_not_exists(IN table_name VARCHAR(64), IN column_name VARCHAR(64), IN alter_sql TEXT)
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = table_name
      AND COLUMN_NAME = column_name
  ) THEN
    SET @sql = alter_sql;
    PREPARE stmt FROM @sql;
    EXECUTE stmt;
    DEALLOCATE PREPARE stmt;
  END IF;
END//
DELIMITER ;

DROP PROCEDURE IF EXISTS add_index_if_not_exists;
DELIMITER //
CREATE PROCEDURE add_index_if_not_exists(IN table_name VARCHAR(64), IN index_name VARCHAR(64), IN alter_sql TEXT)
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM information_schema.STATISTICS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = table_name
      AND INDEX_NAME = index_name
  ) THEN
    SET @sql = alter_sql;
    PREPARE stmt FROM @sql;
    EXECUTE stmt;
    DEALLOCATE PREPARE stmt;
  END IF;
END//
DELIMITER ;

CALL add_column_if_not_exists('users', 'points', 'ALTER TABLE `users` ADD COLUMN `points` INT NOT NULL DEFAULT 0 COMMENT ''积分余额''');
CALL add_column_if_not_exists('users', 'api_token', 'ALTER TABLE `users` ADD COLUMN `api_token` VARCHAR(128) NULL COMMENT ''长期调用 Token''');
CALL add_index_if_not_exists('users', 'uid_users_api_token', 'ALTER TABLE `users` ADD UNIQUE KEY `uid_users_api_token` (`api_token`)');

DROP PROCEDURE IF EXISTS add_column_if_not_exists;
DROP PROCEDURE IF EXISTS add_index_if_not_exists;

CREATE TABLE IF NOT EXISTS `paper_outline_records` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `created_at` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  `updated_at` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  `title` VARCHAR(200) NOT NULL COMMENT '论文标题',
  `request_payload` JSON NULL COMMENT '大纲请求快照',
  `outline_data` JSON NOT NULL COMMENT '大纲生成结果',
  `user_id` INT NOT NULL COMMENT '用户',
  PRIMARY KEY (`id`),
  KEY `idx_outline_user_id` (`user_id`),
  CONSTRAINT `fk_outline_user_id` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='论文大纲记录';

CREATE TABLE IF NOT EXISTS `paper_orders` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `created_at` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  `updated_at` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  `order_sn` VARCHAR(64) NOT NULL COMMENT '论文订单号',
  `title` VARCHAR(200) NOT NULL COMMENT '论文标题',
  `outline_json` JSON NOT NULL COMMENT '用户确认后的大纲',
  `config_form` JSON NULL COMMENT '生成配置快照',
  `template_id` INT NULL COMMENT '模板 ID',
  `selftemp` INT NULL COMMENT '模板类型',
  `service_ids` JSON NULL COMMENT '增值服务 ID',
  `cost_points` INT NOT NULL DEFAULT 200 COMMENT '应扣积分',
  `paid_points` INT NOT NULL DEFAULT 0 COMMENT '已扣积分',
  `status` VARCHAR(32) NOT NULL DEFAULT 'created' COMMENT '订单状态',
  `task_id` VARCHAR(64) NULL COMMENT '生成任务 ID',
  `file_key` VARCHAR(512) NULL COMMENT '七牛文件 key',
  `download_url` VARCHAR(1024) NULL COMMENT '下载链接',
  `last_error` VARCHAR(500) NULL COMMENT '最近一次错误',
  `paid_at` DATETIME(6) NULL COMMENT '扣费时间',
  `started_at` DATETIME(6) NULL COMMENT '开始生成时间',
  `completed_at` DATETIME(6) NULL COMMENT '完成时间',
  `outline_record_id` INT NOT NULL COMMENT '大纲记录',
  `user_id` INT NOT NULL COMMENT '用户',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uid_paper_orders_order_sn` (`order_sn`),
  KEY `idx_paper_orders_user_id` (`user_id`),
  KEY `idx_paper_orders_outline_record_id` (`outline_record_id`),
  CONSTRAINT `fk_paper_orders_user_id` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_paper_orders_outline_record_id` FOREIGN KEY (`outline_record_id`) REFERENCES `paper_outline_records` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='论文订单';
