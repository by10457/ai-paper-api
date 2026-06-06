"""论文生成 Redis 队列 worker。"""

import asyncio

from core.config import settings
from core.logger import logger
from services.thesis.business.order_workflow import run_paid_paper_order
from services.thesis.generation.paper_queue import PaperQueueJob, pop_ready_generation_job
from services.thesis.generation.task_service import run_generation_task


async def run_paper_generation_worker(stop_event: asyncio.Event) -> None:
    """持续消费待生成论文任务，直到收到退出信号。"""

    running_tasks: set[asyncio.Task[None]] = set()
    logger.info("📝 论文生成 worker 已启动，并发上限={}", settings.PAPER_GENERATION_CONCURRENCY)

    try:
        while not stop_event.is_set():
            _forget_done_tasks(running_tasks)
            available_slots = settings.PAPER_GENERATION_CONCURRENCY - len(running_tasks)
            if available_slots > 0:
                await _dispatch_pending_jobs(running_tasks, available_slots)

            try:
                await asyncio.wait_for(stop_event.wait(), timeout=settings.PAPER_WORKER_POLL_SECONDS)
            except TimeoutError:
                pass
    finally:
        if running_tasks:
            logger.info("等待 {} 个论文生成任务结束", len(running_tasks))
            await asyncio.gather(*running_tasks, return_exceptions=True)
        logger.info("📝 论文生成 worker 已停止")


def _forget_done_tasks(running_tasks: set[asyncio.Task[None]]) -> None:
    """清理已结束任务，并记录未被内部处理的异常。"""

    done_tasks = {task for task in running_tasks if task.done()}
    running_tasks.difference_update(done_tasks)
    for task in done_tasks:
        if task.cancelled():
            continue
        exc = task.exception()
        if exc is not None:
            logger.exception("论文生成 worker 子任务异常", exc_info=exc)


async def _dispatch_pending_jobs(running_tasks: set[asyncio.Task[None]], available_slots: int) -> None:
    """从 Redis 队列取出可执行任务并派发到当前进程。"""

    for _ in range(available_slots):
        job = await pop_ready_generation_job()
        if job is None:
            return
        running_tasks.add(asyncio.create_task(_run_queue_job(job)))


async def _run_queue_job(job: PaperQueueJob) -> None:
    """按队列任务类型执行论文生成。"""

    if job.kind == "order":
        await run_paid_paper_order(job.item_id)
    else:
        await run_generation_task(job.item_id)
