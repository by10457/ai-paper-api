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

import asyncio
import os
import socket
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import cast

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

# 路由注册（按版本组织）
from api.v1 import router as v1_router
from core.config import settings
from core.database import close_db, init_db
from core.logger import logger
from core.redis import close_redis, init_redis
from tasks import scheduler as task_scheduler
from tasks.paper_worker import run_paper_generation_worker

PUBLIC_DIR = Path(__file__).resolve().parent / "public"
_NO_CACHE_STATIC_PATHS = {"/", "/index.html", "/_app.config.js"}
_IMMUTABLE_STATIC_EXTS = {
    ".css",
    ".gif",
    ".ico",
    ".jpeg",
    ".jpg",
    ".js",
    ".mjs",
    ".png",
    ".svg",
    ".webp",
    ".woff",
    ".woff2",
}


class SPAStaticFiles(StaticFiles):
    """支持 Vue Router history 模式的静态文件服务。"""

    async def get_response(self, path: str, scope: dict) -> Response:
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code == 404 and not Path(path).suffix:
                return await super().get_response("index.html", scope)
            raise


def _should_start_scheduler() -> bool:
    """判断当前进程是否应该启动 APScheduler。"""

    return settings.APP_DEBUG and settings.SCHEDULER_ENABLED and "PYTEST_CURRENT_TEST" not in os.environ


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
    worker_stop_event: asyncio.Event | None = None
    worker_task: asyncio.Task[None] | None = None

    await init_db()
    await init_redis()

    if _should_start_scheduler():
        task_scheduler.register_jobs()
        task_scheduler.scheduler.start()
        worker_stop_event = asyncio.Event()
        worker_task = asyncio.create_task(run_paper_generation_worker(worker_stop_event))
        logger.info("⏰ 开发环境定时任务调度器已启动")
    elif settings.APP_DEBUG:
        logger.info("⏸️ 开发环境定时任务已通过 SCHEDULER_ENABLED=false 关闭")

    _log_access_urls()
    logger.info("✅ 应用启动完成，开始接收请求")
    yield

    # ── Shutdown ──────────────────────────────────────────
    logger.info("🛑 应用正在关闭...")

    if task_scheduler.scheduler.running:
        task_scheduler.scheduler.shutdown(wait=False)
        logger.info("⏰ 定时任务调度器已停止")

    if worker_stop_event is not None and worker_task is not None:
        worker_stop_event.set()
        await worker_task

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
# Vite 构建产物中的 JS/CSS 文件名带内容 hash，可长缓存；HTML 入口和运行时配置
# 需要禁缓存，避免发布后仍加载旧入口或旧 API 地址。


@app.middleware("http")
async def no_cache_for_static(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    response = await call_next(request)
    path = request.url.path
    content_type = response.headers.get("content-type", "")
    if path in _NO_CACHE_STATIC_PATHS or path.endswith(".html") or content_type.startswith("text/html"):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    elif response.status_code == 200 and any(path.endswith(ext) for ext in _IMMUTABLE_STATIC_EXTS):
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    return response


# ── 路由挂载 ──────────────────────────────────────────────────

app.include_router(v1_router, prefix="/api/v1")

# ── 静态文件（最后挂载，避免拦截 API 请求）──────────────────────

if PUBLIC_DIR.exists():
    app.mount("/", SPAStaticFiles(directory=str(PUBLIC_DIR), html=True), name="static")
else:
    logger.warning(f"静态目录不存在：{PUBLIC_DIR}")
