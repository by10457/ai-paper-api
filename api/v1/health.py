"""健康检查接口路由。"""

from fastapi import APIRouter
from tortoise import connections

from core import redis as redis_module
from core.logger import logger
from schemas.common import Response

router = APIRouter()


async def _check_mysql() -> bool:
    """探测默认 MySQL 连接是否可用。"""

    try:
        conn = connections.get("default")
        await conn.execute_query("SELECT 1")
        return True
    except Exception as exc:  # noqa: BLE001
        # 健康检查需要覆盖连接池、网络、SQL 执行等多类异常，统一降级为不可用状态。
        logger.debug("健康检查 MySQL 探测失败：{}", exc)
        return False


async def _check_redis() -> bool:
    """探测 Redis 连接是否可用。"""

    if redis_module.redis_client is None:
        return False
    try:
        await redis_module.redis_client.ping()
        return True
    except Exception as exc:  # noqa: BLE001
        # Redis 客户端可能抛出连接、超时、认证等不同异常，健康检查只关心可用性。
        logger.debug("健康检查 Redis 探测失败：{}", exc)
        return False


def _status_text(is_ok: bool) -> str:
    """将布尔探测结果转换为健康检查响应文本。"""

    return "ok" if is_ok else "error"


@router.get("", summary="健康检查")
async def health_check() -> Response[dict[str, str]]:
    """检查应用、数据库、Redis 连接状态，供运维监控和探针调用。"""

    mysql_ok = await _check_mysql()
    redis_ok = await _check_redis()
    return Response.ok(
        data={
            "status": "ok" if (mysql_ok and redis_ok) else "degraded",
            "mysql": _status_text(mysql_ok),
            "redis": _status_text(redis_ok),
        }
    )
