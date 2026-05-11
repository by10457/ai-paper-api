"""
v1 版本路由汇总

新增模块时，在这里 include 进来即可。
"""

from fastapi import APIRouter

from api.v1.auth import router as auth_router
from api.v1.health import router as health_router
from api.v1.user import router as user_router

router = APIRouter()

router.include_router(health_router, prefix="/health", tags=["健康检查"])
router.include_router(auth_router, prefix="/auth", tags=["认证"])
router.include_router(user_router, prefix="/users", tags=["用户"])
