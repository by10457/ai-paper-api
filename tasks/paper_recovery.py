"""论文生成补偿任务。"""

import asyncio
from datetime import timedelta

from tortoise import timezone

from core.logger import logger
from models.paper import PaperDirectTask, PaperOrder
from services.thesis.business.order_workflow import run_paid_paper_order
from services.thesis.generation.task_service import run_direct_generate_task

RECOVERY_BATCH_SIZE = 5
STALE_GENERATING_MINUTES = 60


async def recover_paid_paper_jobs() -> None:
    """恢复已扣费但尚未启动生成的论文任务。"""

    await _reset_stale_generating_jobs()

    orders = await PaperOrder.filter(status="paid").order_by("id").limit(RECOVERY_BATCH_SIZE)
    direct_tasks = await PaperDirectTask.filter(status="paid").order_by("id").limit(RECOVERY_BATCH_SIZE)

    for order in orders:
        asyncio.create_task(run_paid_paper_order(order.id))
    for direct_task in direct_tasks:
        asyncio.create_task(run_direct_generate_task(direct_task.id))

    if orders or direct_tasks:
        logger.info(f"已触发论文生成补偿任务：orders={len(orders)}, direct_tasks={len(direct_tasks)}")


async def _reset_stale_generating_jobs() -> None:
    """把疑似被进程中断的生成中任务放回补偿队列。"""

    cutoff = timezone.now() - timedelta(minutes=STALE_GENERATING_MINUTES)
    stale_orders = (
        await PaperOrder.filter(status="generating", started_at__lt=cutoff)
        .order_by("id")
        .limit(RECOVERY_BATCH_SIZE)
    )
    stale_direct_tasks = (
        await PaperDirectTask.filter(status="generating", started_at__lt=cutoff)
        .order_by("id")
        .limit(RECOVERY_BATCH_SIZE)
    )

    for order in stale_orders:
        order.status = "paid"
        order.task_id = None  # type: ignore[assignment]
        order.started_at = None  # type: ignore[assignment]
        order.last_error = "生成任务长时间未完成，已加入自动补偿队列"
        await order.save(update_fields=["status", "task_id", "started_at", "last_error", "updated_at"])

    for direct_task in stale_direct_tasks:
        direct_task.status = "paid"
        direct_task.started_at = None  # type: ignore[assignment]
        direct_task.last_error = "生成任务长时间未完成，已加入自动补偿队列"
        await direct_task.save(update_fields=["status", "started_at", "last_error", "updated_at"])

    if stale_orders or stale_direct_tasks:
        logger.warning(
            f"已重置超时生成任务：orders={len(stale_orders)}, direct_tasks={len(stale_direct_tasks)}"
        )
