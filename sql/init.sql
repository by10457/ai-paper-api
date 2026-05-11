-- 初始化数据库（如果还没建库，先手动执行这里）
-- CREATE DATABASE IF NOT EXISTS your_database CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
-- USE your_database;

-- 以下表结构由 aerich 迁移管理，此文件可放一些初始化数据。

-- 当前模板内置用户表结构，对应 models/user.py。
-- 生产环境推荐通过 aerich 迁移生成和维护表结构；此处用于初始化参考或手动建表。
CREATE TABLE IF NOT EXISTS `users` (
  `id` int NOT NULL AUTO_INCREMENT,
  `created_at` datetime(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  `updated_at` datetime(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  `username` varchar(64) NOT NULL COMMENT '用户名',
  `hashed_password` varchar(256) NOT NULL COMMENT '哈希密码',
  `avatar` varchar(512) DEFAULT NULL COMMENT '头像地址',
  `nickname` varchar(64) DEFAULT NULL COMMENT '昵称',
  `email` varchar(128) NOT NULL COMMENT '邮箱',
  PRIMARY KEY (`id`),
  UNIQUE KEY `username` (`username`),
  UNIQUE KEY `email` (`email`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='用户表';
