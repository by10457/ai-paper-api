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
CALL add_column_if_not_exists('users', 'api_token_created_at', 'ALTER TABLE `users` ADD COLUMN `api_token_created_at` DATETIME(6) NULL COMMENT ''调用 Token 创建时间''');
CALL add_column_if_not_exists('users', 'api_token_last_used_at', 'ALTER TABLE `users` ADD COLUMN `api_token_last_used_at` DATETIME(6) NULL COMMENT ''调用 Token 最近使用时间''');
CALL add_column_if_not_exists('users', 'api_token_call_count', 'ALTER TABLE `users` ADD COLUMN `api_token_call_count` INT NOT NULL DEFAULT 0 COMMENT ''调用 Token 使用次数''');
CALL add_column_if_not_exists('users', 'role', 'ALTER TABLE `users` ADD COLUMN `role` VARCHAR(32) NOT NULL DEFAULT ''user'' COMMENT ''角色：user/admin''');
CALL add_column_if_not_exists('users', 'is_disabled', 'ALTER TABLE `users` ADD COLUMN `is_disabled` TINYINT(1) NOT NULL DEFAULT 0 COMMENT ''是否禁用''');
CALL add_column_if_not_exists('users', 'last_login_at', 'ALTER TABLE `users` ADD COLUMN `last_login_at` DATETIME(6) NULL COMMENT ''最近登录时间''');
CALL add_index_if_not_exists('users', 'uid_users_api_token', 'ALTER TABLE `users` ADD UNIQUE KEY `uid_users_api_token` (`api_token`)');

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
  `refunded_points` INT NOT NULL DEFAULT 0 COMMENT '已退积分',
  `status` VARCHAR(32) NOT NULL DEFAULT 'created' COMMENT '订单状态',
  `task_id` VARCHAR(64) NULL COMMENT '生成任务 ID',
  `file_key` VARCHAR(512) NULL COMMENT '七牛文件 key',
  `download_url` VARCHAR(1024) NULL COMMENT '下载链接',
  `last_error` VARCHAR(500) NULL COMMENT '最近一次错误',
  `paid_at` DATETIME(6) NULL COMMENT '扣费时间',
  `refunded_at` DATETIME(6) NULL COMMENT '退积分时间',
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

CALL add_column_if_not_exists('paper_orders', 'refunded_points', 'ALTER TABLE `paper_orders` ADD COLUMN `refunded_points` INT NOT NULL DEFAULT 0 COMMENT ''已退积分''');
CALL add_column_if_not_exists('paper_orders', 'refunded_at', 'ALTER TABLE `paper_orders` ADD COLUMN `refunded_at` DATETIME(6) NULL COMMENT ''退积分时间''');

CREATE TABLE IF NOT EXISTS `point_ledgers` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `created_at` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  `updated_at` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  `change_type` VARCHAR(32) NOT NULL COMMENT '流水类型',
  `delta` INT NOT NULL COMMENT '积分变化',
  `balance_after` INT NOT NULL COMMENT '变更后余额',
  `reason` VARCHAR(255) NOT NULL COMMENT '变更原因',
  `metadata` JSON NULL COMMENT '扩展信息',
  `user_id` INT NOT NULL COMMENT '积分所属用户',
  `operator_id` INT NULL COMMENT '操作人',
  `order_id` INT NULL COMMENT '关联订单',
  PRIMARY KEY (`id`),
  KEY `idx_point_ledgers_user_id` (`user_id`),
  KEY `idx_point_ledgers_operator_id` (`operator_id`),
  KEY `idx_point_ledgers_order_id` (`order_id`),
  CONSTRAINT `fk_point_ledgers_user_id` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_point_ledgers_operator_id` FOREIGN KEY (`operator_id`) REFERENCES `users` (`id`) ON DELETE SET NULL,
  CONSTRAINT `fk_point_ledgers_order_id` FOREIGN KEY (`order_id`) REFERENCES `paper_orders` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='积分流水';

CREATE TABLE IF NOT EXISTS `recharge_orders` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `created_at` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  `updated_at` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  `order_sn` VARCHAR(64) NOT NULL COMMENT '充值申请单号',
  `points` INT NOT NULL COMMENT '申请充值积分',
  `amount` DECIMAL(10,2) NOT NULL COMMENT '折算金额',
  `pay_channel` VARCHAR(32) NOT NULL DEFAULT 'manual' COMMENT '支付/沟通渠道',
  `status` VARCHAR(32) NOT NULL DEFAULT 'pending' COMMENT 'pending/approved/rejected',
  `remark` VARCHAR(500) NULL COMMENT '用户备注',
  `admin_remark` VARCHAR(500) NULL COMMENT '管理员备注',
  `reviewed_at` DATETIME(6) NULL COMMENT '审核时间',
  `user_id` INT NOT NULL COMMENT '申请用户',
  `reviewer_id` INT NULL COMMENT '审核管理员',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uid_recharge_orders_order_sn` (`order_sn`),
  KEY `idx_recharge_orders_user_id` (`user_id`),
  KEY `idx_recharge_orders_reviewer_id` (`reviewer_id`),
  KEY `idx_recharge_orders_status` (`status`),
  CONSTRAINT `fk_recharge_orders_user_id` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_recharge_orders_reviewer_id` FOREIGN KEY (`reviewer_id`) REFERENCES `users` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='用户积分充值申请';

CREATE TABLE IF NOT EXISTS `model_configs` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `created_at` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  `updated_at` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  `config_type` VARCHAR(32) NOT NULL COMMENT '用途',
  `provider` VARCHAR(64) NOT NULL COMMENT '模型供应商',
  `model_name` VARCHAR(128) NOT NULL COMMENT '模型名称',
  `api_base_url` VARCHAR(255) NOT NULL COMMENT 'API Base URL',
  `api_key` VARCHAR(1024) NOT NULL COMMENT 'API Key',
  `temperature` DOUBLE NOT NULL DEFAULT 0.7 COMMENT '温度',
  `max_tokens` INT NOT NULL DEFAULT 4096 COMMENT '最大 token',
  `timeout_seconds` INT NOT NULL DEFAULT 120 COMMENT '超时时间',
  `is_enabled` TINYINT(1) NOT NULL DEFAULT 1 COMMENT '是否启用',
  `is_default` TINYINT(1) NOT NULL DEFAULT 0 COMMENT '是否默认',
  `remark` VARCHAR(255) NULL COMMENT '备注',
  PRIMARY KEY (`id`),
  KEY `idx_model_configs_type` (`config_type`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='大模型配置';

CREATE TABLE IF NOT EXISTS `model_call_logs` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `created_at` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  `updated_at` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  `config_type` VARCHAR(32) NOT NULL COMMENT '调用用途',
  `provider` VARCHAR(64) NOT NULL COMMENT '模型供应商',
  `model_name` VARCHAR(128) NOT NULL COMMENT '模型名称',
  `input_tokens` INT NOT NULL DEFAULT 0 COMMENT '输入 token',
  `output_tokens` INT NOT NULL DEFAULT 0 COMMENT '输出 token',
  `latency_ms` INT NOT NULL DEFAULT 0 COMMENT '耗时毫秒',
  `status` VARCHAR(32) NOT NULL COMMENT '调用状态',
  `error_message` VARCHAR(500) NULL COMMENT '错误信息',
  `user_id` INT NULL COMMENT '用户',
  `order_id` INT NULL COMMENT '订单',
  `model_config_id` INT NULL COMMENT '模型配置',
  PRIMARY KEY (`id`),
  KEY `idx_model_call_logs_user_id` (`user_id`),
  KEY `idx_model_call_logs_order_id` (`order_id`),
  KEY `idx_model_call_logs_model_config_id` (`model_config_id`),
  CONSTRAINT `fk_model_call_logs_user_id` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE SET NULL,
  CONSTRAINT `fk_model_call_logs_order_id` FOREIGN KEY (`order_id`) REFERENCES `paper_orders` (`id`) ON DELETE SET NULL,
  CONSTRAINT `fk_model_call_logs_model_config_id` FOREIGN KEY (`model_config_id`) REFERENCES `model_configs` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='大模型调用日志';

CREATE TABLE IF NOT EXISTS `system_configs` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `created_at` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  `updated_at` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  `key` VARCHAR(128) NOT NULL COMMENT '配置键',
  `value` TEXT NOT NULL COMMENT '配置值',
  `description` VARCHAR(255) NULL COMMENT '说明',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uid_system_configs_key` (`key`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='系统配置';

CREATE TABLE IF NOT EXISTS `audit_logs` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `created_at` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  `updated_at` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  `action` VARCHAR(64) NOT NULL COMMENT '操作类型',
  `target_type` VARCHAR(64) NOT NULL COMMENT '目标类型',
  `target_id` VARCHAR(64) NULL COMMENT '目标 ID',
  `summary` VARCHAR(500) NOT NULL COMMENT '操作摘要',
  `before` JSON NULL COMMENT '变更前',
  `after` JSON NULL COMMENT '变更后',
  `ip_address` VARCHAR(64) NULL COMMENT 'IP',
  `operator_id` INT NULL COMMENT '操作人',
  PRIMARY KEY (`id`),
  KEY `idx_audit_logs_operator_id` (`operator_id`),
  CONSTRAINT `fk_audit_logs_operator_id` FOREIGN KEY (`operator_id`) REFERENCES `users` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='审计日志';

DROP PROCEDURE IF EXISTS add_column_if_not_exists;
DROP PROCEDURE IF EXISTS add_index_if_not_exists;
