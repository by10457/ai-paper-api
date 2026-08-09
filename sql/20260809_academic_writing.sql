-- 开题报告、文献综述、任务书共用任务模型增量脚本。
-- 执行前请备份数据库；脚本可重复执行，不会覆盖已有业务数据。

DROP PROCEDURE IF EXISTS `migrate_academic_writing_20260809`;
DELIMITER $$
CREATE PROCEDURE `migrate_academic_writing_20260809`()
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'paper_orders' AND COLUMN_NAME = 'document_type'
  ) THEN
    ALTER TABLE `paper_orders`
      ADD COLUMN `document_type` varchar(32) NOT NULL DEFAULT 'thesis' COMMENT '文档类型' AFTER `order_sn`;
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'paper_generation_tasks' AND COLUMN_NAME = 'document_type'
  ) THEN
    ALTER TABLE `paper_generation_tasks`
      ADD COLUMN `document_type` varchar(32) NOT NULL DEFAULT 'thesis' COMMENT '文档类型' AFTER `task_id`;
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'paper_generation_tasks' AND COLUMN_NAME = 'result_data'
  ) THEN
    ALTER TABLE `paper_generation_tasks`
      ADD COLUMN `result_data` json NULL COMMENT '结构化文档生成结果' AFTER `result_summary`;
  END IF;

  UPDATE `paper_orders` SET `document_type` = 'thesis' WHERE `document_type` IS NULL OR `document_type` = '';
  UPDATE `paper_generation_tasks` SET `document_type` = 'thesis' WHERE `document_type` IS NULL OR `document_type` = '';

  IF NOT EXISTS (
    SELECT 1 FROM information_schema.STATISTICS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'paper_orders'
      AND INDEX_NAME = 'idx_paper_orders_user_type_time'
  ) THEN
    ALTER TABLE `paper_orders`
      ADD KEY `idx_paper_orders_user_type_time` (`user_id`, `document_type`, `created_at`);
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM information_schema.STATISTICS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'paper_generation_tasks'
      AND INDEX_NAME = 'idx_paper_generation_tasks_type_status'
  ) THEN
    ALTER TABLE `paper_generation_tasks`
      ADD KEY `idx_paper_generation_tasks_type_status` (`document_type`, `status`, `updated_at`);
  END IF;
END$$
DELIMITER ;
CALL `migrate_academic_writing_20260809`();
DROP PROCEDURE IF EXISTS `migrate_academic_writing_20260809`;
