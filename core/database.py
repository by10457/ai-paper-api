"""
MySQL 连接管理（Tortoise-ORM）

连接的初始化和关闭在 app.py lifespan 或 tasks.runner 中调用，
业务代码中直接使用 ORM 模型即可，无需手动获取连接。

aerich 迁移命令：
    uv run aerich init -t core.database.TORTOISE_ORM   # 仅首次初始化
    uv run aerich migrate --name "描述"                 # 生成迁移文件
    uv run aerich upgrade                               # 应用迁移
"""

from tortoise import Tortoise, connections

from core.config import settings
from core.logger import logger

# 暴露给 aerich CLI 使用的配置入口
TORTOISE_ORM = settings.TORTOISE_ORM
db_connected = False


async def init_db() -> bool:
    """初始化数据库连接池，在应用启动时调用。"""
    global db_connected
    logger.info("正在连接 MySQL...")
    try:
        await Tortoise.init(config=settings.TORTOISE_ORM)
        conn = connections.get("default")
        await conn.execute_query("SELECT 1")

        # 默认不在应用启动时自动建表，表结构由 aerich 迁移或 sql/init.sql 管理。
        # 仅开发调试需要快速生成缺失表时，设置 DB_GENERATE_SCHEMAS=true。
        if settings.DB_GENERATE_SCHEMAS:
            logger.warning("DB_GENERATE_SCHEMAS=true，正在自动生成缺失表结构，仅建议开发环境使用")
            await Tortoise.generate_schemas(safe=True)
    except Exception as exc:
        db_connected = False
        await Tortoise.close_connections()
        logger.warning(f"MySQL 未连接，应用将继续启动：{type(exc).__name__}: {exc}")
        return False

    db_connected = True
    logger.info(f"MySQL 连接成功：{settings.MYSQL_HOST}:{settings.MYSQL_PORT}/{settings.MYSQL_DB}")
    return True


async def close_db() -> None:
    """关闭数据库连接池，在应用关闭时调用。"""
    global db_connected
    if db_connected:
        await Tortoise.close_connections()
        db_connected = False
        logger.info("MySQL 连接已关闭")
