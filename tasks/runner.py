"""
定时任务独立运行入口。

使用方式：
    uv run python -m tasks.runner

生产环境由容器启动脚本作为独立进程启动，避免 API 多 worker 重复执行任务。
"""

import asyncio
import signal
from types import FrameType

from core.config import settings
from core.database import close_db, init_db
from core.logger import logger
from core.redis import close_redis, init_redis
from tasks.scheduler import register_jobs, scheduler


def _install_signal_handlers(stop_event: asyncio.Event) -> None:
    """注册退出信号，确保容器停止时能清理连接。"""
    loop = asyncio.get_running_loop()

    def request_shutdown(signal_name: str) -> None:
        logger.info(f"收到退出信号 {signal_name}，准备停止定时任务进程")
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, request_shutdown, sig.name)
        except NotImplementedError:

            def fallback_handler(
                _signum: int,
                _frame: FrameType | None,
                *,
                signal_name: str = sig.name,
            ) -> None:
                loop.call_soon_threadsafe(request_shutdown, signal_name)

            signal.signal(sig, fallback_handler)


async def run_scheduler() -> None:
    """初始化基础设施并持续运行 APScheduler。"""
    if not settings.SCHEDULER_ENABLED:
        logger.info("⏸️ 定时任务已通过 SCHEDULER_ENABLED=false 关闭")
        return

    stop_event = asyncio.Event()
    _install_signal_handlers(stop_event)

    logger.info("🚀 定时任务进程启动中")

    try:
        await init_db()
        await init_redis()

        register_jobs()
        scheduler.start()
        logger.info("⏰ 定时任务调度器已启动")

        await stop_event.wait()
    finally:
        logger.info("🛑 定时任务进程正在关闭...")

        if scheduler.running:
            scheduler.shutdown(wait=False)
            logger.info("⏰ 定时任务调度器已停止")

        await close_redis()
        await close_db()

        logger.info("👋 定时任务进程已安全关闭")


def main() -> None:
    """命令行入口。"""
    asyncio.run(run_scheduler())


if __name__ == "__main__":
    main()
