from fastapi import APIRouter
from tortoise import connections

from core import redis as redis_module
from core.logger import logger
from schemas.common import Response

router = APIRouter()


@router.get("", summary="健康检查")
async def health_check() -> Response[dict[str, str]]:
    """
    检查应用、数据库、Redis 连接状态。
    运维监控、K8s 探针可调用此接口。
    """
    db_ok = False
    redis_ok = False

    try:
        conn = connections.get("default")
        await conn.execute_query("SELECT 1")
        db_ok = True
    except Exception as exc:
        logger.debug(f"健康检查 MySQL 探测失败：{exc}")

    try:
        if redis_module.redis_client:
            await redis_module.redis_client.ping()
            redis_ok = True
    except Exception as exc:
        logger.debug(f"健康检查 Redis 探测失败：{exc}")

    return Response.ok(
        data={
            "status": "ok" if (db_ok and redis_ok) else "degraded",
            "mysql": "ok" if db_ok else "error",
            "redis": "ok" if redis_ok else "error",
        }
    )
