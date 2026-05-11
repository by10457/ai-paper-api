"""
Redis 连接管理

采用模块级单例模式：
    from core import redis as redis_module
    if redis_module.redis_client is not None:
        await redis_module.redis_client.set("key", "value")

连接池在 app.py lifespan 或 tasks.runner 中初始化/关闭，
其他模块需要读取 redis_client 时，应通过 redis_module.redis_client 获取最新引用。
"""

import redis.asyncio as aioredis
from redis.asyncio import Redis

from core.config import settings
from core.logger import logger

# 模块级单例，整个应用共享同一个连接池
redis_client: Redis | None = None


async def init_redis() -> bool:
    """初始化 Redis 连接池，在应用启动时调用。"""
    global redis_client
    logger.info("正在连接 Redis...")
    client = aioredis.from_url(
        settings.REDIS_URL,
        encoding="utf-8",
        decode_responses=True,
        max_connections=settings.REDIS_MAX_CONNECTIONS,
    )
    # 验证连接
    try:
        await client.ping()
    except Exception as exc:
        await client.aclose()
        redis_client = None
        logger.warning(f"Redis 未连接，应用将继续启动：{type(exc).__name__}: {exc}")
        return False

    redis_client = client
    logger.info(f"Redis 连接成功：{settings.REDIS_HOST}:{settings.REDIS_PORT}/{settings.REDIS_DB}")
    return True


async def close_redis() -> None:
    """关闭 Redis 连接池，在应用关闭时调用。"""
    global redis_client
    if redis_client is not None:
        await redis_client.aclose()
        redis_client = None
        logger.info("Redis 连接已关闭")


def get_redis() -> Redis:
    """
    供 FastAPI 依赖注入使用（可选）。
    需要允许 Redis 未初始化时优雅降级的地方，可直接读取 redis_module.redis_client。
    """
    if redis_client is None:
        raise RuntimeError("Redis 尚未初始化，请检查 lifespan 是否正确执行")
    return redis_client
