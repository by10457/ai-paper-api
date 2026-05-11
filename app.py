"""
FastAPI 应用实例 + 生命周期管理

【生命周期顺序】
startup:
  1. 初始化日志（import 即生效）
  2. 连接 MySQL
  3. 连接 Redis
  4. 开发环境注册并启动定时任务

shutdown（反序）:
  1. 停止开发环境定时任务
  2. 关闭 Redis
  3. 关闭 MySQL
"""

import socket
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import cast

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

# 路由注册（按版本组织）
from api.v1 import router as v1_router
from core.config import settings
from core.database import close_db, init_db
from core.logger import logger
from core.redis import close_redis, init_redis
from tasks.scheduler import register_jobs, scheduler

PUBLIC_DIR = Path(__file__).resolve().parent / "public"
_NO_CACHE_EXTS = {".js", ".css", ".html"}


def _detect_lan_ip() -> str | None:
    """探测当前机器在局域网中的出口 IP。"""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            host = cast(str, sock.getsockname()[0])
    except OSError:
        return None
    if host.startswith("127."):
        return None
    return host


def _log_access_urls() -> None:
    """输出本地和局域网访问地址。"""
    local_base = f"http://localhost:{settings.APP_PORT}"
    logger.info("FastAPI service is ready")
    logger.info(f"Local site: {local_base}/index.html")
    if settings.APP_DEBUG:
        logger.info(f"API docs: {local_base}/docs")

    if settings.APP_HOST == "0.0.0.0":
        lan_ip = _detect_lan_ip()
        if lan_ip:
            lan_base = f"http://{lan_ip}:{settings.APP_PORT}"
            logger.info(f"LAN site: {lan_base}/index.html")
            if settings.APP_DEBUG:
                logger.info(f"LAN docs: {lan_base}/docs")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """
    应用生命周期管理。
    yield 前 = startup，yield 后 = shutdown。
    """
    # ── Startup ───────────────────────────────────────────
    logger.info(f"🚀 {settings.APP_NAME} 启动中 [env={settings.APP_ENV}]")

    await init_db()
    await init_redis()

    if settings.APP_DEBUG and settings.SCHEDULER_ENABLED:
        register_jobs()
        scheduler.start()
        logger.info("⏰ 开发环境定时任务调度器已启动")
    elif settings.APP_DEBUG:
        logger.info("⏸️ 开发环境定时任务已通过 SCHEDULER_ENABLED=false 关闭")

    _log_access_urls()
    logger.info("✅ 应用启动完成，开始接收请求")
    yield

    # ── Shutdown ──────────────────────────────────────────
    logger.info("🛑 应用正在关闭...")

    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("⏰ 定时任务调度器已停止")

    await close_redis()
    await close_db()

    logger.info("👋 应用已安全关闭")


# ── FastAPI 实例 ──────────────────────────────────────────────

app = FastAPI(
    title=settings.APP_NAME,
    version="1.0.0",
    docs_url="/docs" if settings.APP_DEBUG else None,  # 生产环境关闭文档
    redoc_url="/redoc" if settings.APP_DEBUG else None,
    lifespan=lifespan,
)

# ── 中间件 ────────────────────────────────────────────────────

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 生产环境改为具体域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── 静态资源缓存控制中间件 ──────────────────────────────────────
# StaticFiles 默认不设置 Cache-Control，浏览器会按启发式规则自行缓存，
# 导致修改 JS/CSS/HTML 后刷新页面仍拿到旧文件。
# 此中间件对静态入口和 .js/.css/.html 强制加 no-cache，开发阶段始终获取最新版本。


@app.middleware("http")
async def no_cache_for_static(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    response = await call_next(request)
    path = request.url.path
    if path == "/" or any(path.endswith(ext) for ext in _NO_CACHE_EXTS):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


# ── 路由挂载 ──────────────────────────────────────────────────

app.include_router(v1_router, prefix="/api/v1")

# ── 静态文件（最后挂载，避免拦截 API 请求）──────────────────────

if PUBLIC_DIR.exists():
    app.mount("/", StaticFiles(directory=str(PUBLIC_DIR), html=True), name="static")
else:
    logger.warning(f"静态目录不存在：{PUBLIC_DIR}")
