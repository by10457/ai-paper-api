"""论文服务定时任务调度器。"""

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from core.logger import logger
from tasks.paper_recovery import recover_paid_paper_jobs

SCHEDULER_MISFIRE_GRACE_SECONDS = 30


def _create_scheduler() -> AsyncIOScheduler:
    return AsyncIOScheduler(
        timezone="Asia/Shanghai",
        job_defaults={
            "coalesce": True,
            "misfire_grace_time": SCHEDULER_MISFIRE_GRACE_SECONDS,
            "max_instances": 1,
        },
    )


scheduler = _create_scheduler()


def _scheduler_event_loop_closed() -> bool:
    event_loop = getattr(scheduler, "_eventloop", None)
    return bool(event_loop and event_loop.is_closed())


def register_jobs() -> None:
    """注册论文生成补偿任务。"""

    global scheduler

    if _scheduler_event_loop_closed():
        scheduler = _create_scheduler()

    scheduler.add_job(
        recover_paid_paper_jobs,
        trigger=IntervalTrigger(seconds=60),
        id="paper_generation_recovery",
        name="论文生成补偿",
        replace_existing=True,
    )

    logger.info(f"✅ 已注册 {len(scheduler.get_jobs())} 个定时任务")
