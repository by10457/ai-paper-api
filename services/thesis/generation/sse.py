"""论文生成 SSE 状态推送服务。"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import suppress

from pydantic import BaseModel

from core.logger import logger
from models.user import User

SSE_POLL_SECONDS = 1.0
TERMINAL_ORDER_STATUSES = {"completed", "failed", "refunded"}

_active_user_orders: dict[int, set[str]] = {}


async def stream_order_status_events[T: BaseModel](
    user: User,
    order_sn: str,
    status_loader: Callable[[User, str], Awaitable[T]],
) -> AsyncIterator[str]:
    """持续推送指定订单状态，终态后自动结束。"""

    _register_connection(user.id, order_sn)
    last_payload = ""
    try:
        while True:
            status = await status_loader(user, order_sn)
            payload = status.model_dump(mode="json")
            data = json.dumps(payload, ensure_ascii=False)
            if data != last_payload:
                last_payload = data
                yield _format_sse("status", data)
            if str(payload.get("status")) in TERMINAL_ORDER_STATUSES:
                break
            await asyncio.sleep(SSE_POLL_SECONDS)
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.warning("论文生成 SSE 连接异常: user_id={}, order_sn={}, err={}", user.id, order_sn, exc)
        error_payload = json.dumps({"message": "状态连接异常，请刷新页面重试"}, ensure_ascii=False)
        with suppress(Exception):
            yield _format_sse("error", error_payload)
    finally:
        _unregister_connection(user.id, order_sn)


def active_sse_connections() -> dict[int, list[str]]:
    """返回当前活跃 SSE 连接快照，便于调试和后续管理页展示。"""

    return {user_id: sorted(order_sns) for user_id, order_sns in _active_user_orders.items()}


def _register_connection(user_id: int, order_sn: str) -> None:
    _active_user_orders.setdefault(user_id, set()).add(order_sn)
    logger.info("论文生成 SSE 已连接: user_id={}, order_sn={}", user_id, order_sn)


def _unregister_connection(user_id: int, order_sn: str) -> None:
    order_sns = _active_user_orders.get(user_id)
    if order_sns is None:
        return
    order_sns.discard(order_sn)
    if not order_sns:
        _active_user_orders.pop(user_id, None)
    logger.info("论文生成 SSE 已断开: user_id={}, order_sn={}", user_id, order_sn)


def _format_sse(event: str, data: str) -> str:
    return f"event: {event}\ndata: {data}\n\n"


__all__ = ["active_sse_connections", "stream_order_status_events"]
