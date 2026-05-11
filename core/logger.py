"""
日志配置（基于 loguru）

使用方式：
    from core.logger import logger
    logger.info("启动中...")
    logger.error("出错了: {}", err)
"""

import sys

from loguru import logger

from core.config import settings

# 清除默认的 handler
logger.remove()

# 控制台输出（开发友好的彩色格式）
logger.add(
    sys.stdout,
    level=settings.LOG_LEVEL,
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
    colorize=True,
)

# 文件输出（按天切割，保留 30 天）
logger.add(
    settings.LOG_FILE,
    level=settings.LOG_LEVEL,
    format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{line} - {message}",
    rotation="00:00",  # 每天零点切割
    retention="30 days",  # 保留 30 天
    compression="zip",  # 旧日志压缩
    encoding="utf-8",
)

__all__ = ["logger"]
