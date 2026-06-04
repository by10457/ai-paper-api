"""论文生成 Redis 队列。"""

from __future__ import annotations

import time
from collections.abc import Awaitable
from dataclasses import dataclass
from inspect import isawaitable
from typing import Literal, cast

from tortoise import timezone
from tortoise.expressions import Q

from core import redis as redis_module
from core.logger import logger
from models.paper import PaperDirectTask, PaperOrder

PAPER_QUEUE_READY_KEY = "ai-paper:queue:paper:ready"
PAPER_QUEUE_DELAYED_KEY = "ai-paper:queue:paper:delayed"
PAPER_QUEUE_ENQUEUED_KEY = "ai-paper:queue:paper:enqueued"

_ENQUEUE_READY_SCRIPT = """
local added = redis.call('SADD', KEYS[1], ARGV[1])
if added == 1 then
    redis.call('RPUSH', KEYS[2], ARGV[1])
end
return added
"""

_ENQUEUE_DELAYED_SCRIPT = """
local added = redis.call('SADD', KEYS[1], ARGV[1])
if added == 1 then
    redis.call('ZADD', KEYS[2], ARGV[2], ARGV[1])
end
return added
"""

_MOVE_DUE_DELAYED_SCRIPT = """
local payloads = redis.call('ZRANGEBYSCORE', KEYS[1], '-inf', ARGV[1], 'LIMIT', 0, ARGV[2])
local moved = 0
for _, payload in ipairs(payloads) do
    if redis.call('ZREM', KEYS[1], payload) == 1 then
        redis.call('RPUSH', KEYS[2], payload)
        moved = moved + 1
    end
end
return moved
"""

PaperQueueKind = Literal["order", "direct"]


@dataclass(frozen=True)
class PaperQueueJob:
    """论文生成队列中的单个任务。"""

    kind: PaperQueueKind
    item_id: int


def _encode_job(kind: PaperQueueKind, item_id: int) -> str:
    """把任务类型和业务 ID 编码成 Redis 队列载荷。"""

    return f"{kind}:{item_id}"


def _decode_job(payload: str) -> PaperQueueJob | None:
    """解析 Redis 队列载荷，异常数据直接丢弃并记录日志。"""

    kind, separator, raw_item_id = payload.partition(":")
    if separator != ":" or kind not in {"order", "direct"}:
        logger.warning(f"忽略非法论文队列任务：{payload}")
        return None

    try:
        item_id = int(raw_item_id)
    except ValueError:
        logger.warning(f"忽略非法论文队列任务 ID：{payload}")
        return None
    return PaperQueueJob(kind=cast(PaperQueueKind, kind), item_id=item_id)


async def _resolve_redis_result[RedisResultT](value: Awaitable[RedisResultT] | RedisResultT) -> RedisResultT:
    """处理 redis-py 类型标注中的同步/异步联合返回值。"""

    if isawaitable(value):
        return await cast(Awaitable[RedisResultT], value)
    return value


async def enqueue_order_generation(order_id: int, delay_seconds: int = 0) -> bool:
    """把已支付订单加入 Redis 生成队列。"""

    return await _enqueue_generation_job("order", order_id, delay_seconds)


async def enqueue_direct_generation(direct_task_id: int, delay_seconds: int = 0) -> bool:
    """把接口直连生成任务加入 Redis 生成队列。"""

    return await _enqueue_generation_job("direct", direct_task_id, delay_seconds)


async def pop_ready_generation_job() -> PaperQueueJob | None:
    """从 Redis 取出一个可执行论文生成任务。"""

    await move_due_delayed_jobs()
    client = redis_module.redis_client
    if client is None:
        return None

    payload = cast(str | None, await _resolve_redis_result(client.lpop(PAPER_QUEUE_READY_KEY)))
    if payload is None:
        return None
    await _resolve_redis_result(client.srem(PAPER_QUEUE_ENQUEUED_KEY, payload))
    return _decode_job(payload)


async def move_due_delayed_jobs(limit: int = 100) -> int:
    """把到期延迟任务移动到 ready 队列。"""

    client = redis_module.redis_client
    if client is None:
        return 0

    moved = await _resolve_redis_result(
        client.eval(
            _MOVE_DUE_DELAYED_SCRIPT,
            2,
            PAPER_QUEUE_DELAYED_KEY,
            PAPER_QUEUE_READY_KEY,
            str(time.time()),
            str(limit),
        )
    )
    return int(moved)


async def enqueue_pending_paid_jobs(limit: int) -> tuple[int, int]:
    """补投数据库中已支付但还未被 Redis worker 消费的任务。"""

    if redis_module.redis_client is None:
        logger.warning("Redis 未连接，跳过论文生成任务补投")
        return 0, 0

    orders = await _list_due_paid_orders(limit)
    for order in orders:
        await enqueue_order_generation(order.id)

    remaining_limit = max(limit - len(orders), 0)
    direct_tasks = await _list_due_paid_direct_tasks(remaining_limit)
    for direct_task in direct_tasks:
        await enqueue_direct_generation(direct_task.id)

    return len(orders), len(direct_tasks)


async def _enqueue_generation_job(kind: PaperQueueKind, item_id: int, delay_seconds: int) -> bool:
    """按是否延迟写入 Redis ready list 或 delayed zset。"""

    client = redis_module.redis_client
    if client is None:
        logger.warning(f"Redis 未连接，论文生成任务暂未入队：{kind}:{item_id}")
        return False

    payload = _encode_job(kind, item_id)
    if delay_seconds > 0:
        await _resolve_redis_result(
            client.eval(
                _ENQUEUE_DELAYED_SCRIPT,
                2,
                PAPER_QUEUE_ENQUEUED_KEY,
                PAPER_QUEUE_DELAYED_KEY,
                payload,
                str(time.time() + delay_seconds),
            )
        )
    else:
        await _resolve_redis_result(
            client.eval(_ENQUEUE_READY_SCRIPT, 2, PAPER_QUEUE_ENQUEUED_KEY, PAPER_QUEUE_READY_KEY, payload)
        )
    return True


async def _list_due_paid_orders(limit: int) -> list[PaperOrder]:
    """查询当前已到生成时间的已支付订单。"""

    if limit <= 0:
        return []
    eligibility = Q(next_retry_at__isnull=True) | Q(next_retry_at__lte=timezone.now())
    return await PaperOrder.filter(Q(status="paid") & eligibility).order_by("id").limit(limit)


async def _list_due_paid_direct_tasks(limit: int) -> list[PaperDirectTask]:
    """查询当前已到生成时间的接口直连已支付任务。"""

    if limit <= 0:
        return []
    eligibility = Q(next_retry_at__isnull=True) | Q(next_retry_at__lte=timezone.now())
    return await PaperDirectTask.filter(Q(status="paid") & eligibility).order_by("id").limit(limit)
