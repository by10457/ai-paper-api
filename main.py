"""
启动入口

开发环境：
    uv run python main.py
    或
    uv run uvicorn app:app --reload

生产环境（建议配合 supervisor/systemd）：
    APP_DEBUG=false WEB_CONCURRENCY=4 uv run python main.py
"""

import os

import uvicorn

from core.config import settings

DEFAULT_PRODUCTION_WORKERS = 4


def get_worker_count() -> int:
    """根据运行环境计算 Uvicorn worker 数量。"""
    if settings.APP_DEBUG:
        return 1
    if settings.WEB_CONCURRENCY is not None:
        return settings.WEB_CONCURRENCY
    return min(os.cpu_count() or 1, DEFAULT_PRODUCTION_WORKERS)


if __name__ == "__main__":
    uvicorn.run(
        "app:app",
        host=settings.APP_HOST,
        port=settings.APP_PORT,
        reload=settings.APP_DEBUG,  # 开发环境热重载
        workers=get_worker_count(),
        log_level=settings.LOG_LEVEL.lower(),
    )
