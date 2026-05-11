"""
定时任务调度器（APScheduler）

【设计约定】
- 调度器实例在本文件声明（scheduler）
- 每个任务函数写在 tasks/ 目录的对应模块里（如 tasks/cleanup.py）
- 任务注册统一在 register_jobs() 里完成
- 开发环境由 app.py lifespan 启停，生产环境由 tasks.runner 独立进程启停

【任务类型说明】
- interval : 每隔固定时间执行，适合轮询类任务
- cron     : cron 表达式，适合定点执行（如每天凌晨清理）
- date     : 指定某个时间点执行一次（一次性任务）
"""

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from core.logger import logger

# 全局调度器单例（异步模式，与 FastAPI 的事件循环共享）
scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")


# ──────────────────────────────────────────────────────────────
# 任务函数定义区
# 复杂任务可拆分到独立文件，这里 import 进来注册即可
# ──────────────────────────────────────────────────────────────


async def task_health_log() -> None:
    """示例：每分钟打印一次心跳日志。"""
    logger.debug("⏰ 定时任务心跳 - 调度器运行正常")


async def task_daily_cleanup() -> None:
    """示例：每天凌晨 2 点执行数据清理。"""
    logger.info("🧹 开始执行每日数据清理...")
    # TODO: 具体清理逻辑
    logger.info("✅ 每日数据清理完成")


# ──────────────────────────────────────────────────────────────
# 任务注册
# ──────────────────────────────────────────────────────────────


def register_jobs() -> None:
    """
    统一注册所有定时任务。
    在 tasks.runner 的启动阶段调用。
    """
    # 每 60 秒执行一次（interval 模式）
    scheduler.add_job(
        task_health_log,
        trigger=IntervalTrigger(seconds=60),
        id="health_log",
        name="心跳日志",
        replace_existing=True,
    )

    # 每天凌晨 2:00 执行（cron 模式）
    scheduler.add_job(
        task_daily_cleanup,
        trigger=CronTrigger(hour=2, minute=0),
        id="daily_cleanup",
        name="每日数据清理",
        replace_existing=True,
    )

    logger.info(f"✅ 已注册 {len(scheduler.get_jobs())} 个定时任务")
