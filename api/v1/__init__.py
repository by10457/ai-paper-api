"""v1 版本路由汇总。"""

from fastapi import APIRouter

from api.v1.admin import router as admin_router
from api.v1.auth import router as auth_router
from api.v1.health import router as health_router
from api.v1.thesis import router as thesis_router
from api.v1.user import router as user_router

ROUTE_REGISTRY: tuple[tuple[APIRouter, str, tuple[str, ...]], ...] = (
    (health_router, "/health", ("健康检查",)),
    (auth_router, "/auth", ("认证",)),
    (user_router, "/users", ("用户",)),
    (thesis_router, "", ()),
    (admin_router, "", ()),
)

router = APIRouter()

for route, prefix, tags in ROUTE_REGISTRY:
    router.include_router(route, prefix=prefix, tags=list(tags) if tags else None)
