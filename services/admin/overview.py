"""管理端概览统计服务。"""

from __future__ import annotations

from typing import Any

from tortoise import timezone
from tortoise.functions import Sum

from core import redis as redis_module
from core.config import settings
from core.database import db_connected
from models.admin import ModelCallLog, ModelConfig
from models.paper import PaperOrder
from models.user import User
from schemas.admin import AdminOverviewResponse


class AdminOverviewService:
    """提供管理后台首页所需的统计和健康状态。"""

    @staticmethod
    async def overview() -> AdminOverviewResponse:
        """汇总今日、本月和累计指标，并返回基础组件健康状态。"""

        now = timezone.now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        has_model_config = await ModelConfig.filter(is_enabled=True).exists()
        health = {
            "mysql": "ok" if db_connected else "degraded",
            "redis": "ok" if redis_module.redis_client is not None else "degraded",
            "storage": AdminOverviewService._storage_health(),
            "model": "ok" if has_model_config else "unconfigured",
        }

        return AdminOverviewResponse(
            today_user_count=await User.filter(created_at__gte=today_start).count(),
            month_user_count=await User.filter(created_at__gte=month_start).count(),
            total_user_count=await User.all().count(),
            today_order_count=await PaperOrder.filter(created_at__gte=today_start).count(),
            month_order_count=await PaperOrder.filter(created_at__gte=month_start).count(),
            total_order_count=await PaperOrder.all().count(),
            today_spent_points=await AdminOverviewService._sum_paid_points(
                PaperOrder.filter(paid_at__gte=today_start)
            ),
            month_spent_points=await AdminOverviewService._sum_paid_points(
                PaperOrder.filter(paid_at__gte=month_start)
            ),
            total_spent_points=await AdminOverviewService._sum_paid_points(PaperOrder.all()),
            generating_order_count=await PaperOrder.filter(status="generating").count(),
            failed_order_count=await PaperOrder.filter(status="failed").count(),
            completed_order_count=await PaperOrder.filter(status="completed").count(),
            model_call_count=await ModelCallLog.all().count(),
            api_token_call_count=await AdminOverviewService._sum_api_token_calls(),
            health=health,
        )

    @staticmethod
    async def _sum_paid_points(query: Any) -> int:
        """汇总订单已支付积分，空结果按 0 处理。"""

        result = await query.annotate(total=Sum("paid_points")).values("total")
        return int((result[0].get("total") if result else 0) or 0)

    @staticmethod
    async def _sum_api_token_calls() -> int:
        """汇总用户 API Token 调用次数，空结果按 0 处理。"""

        result = await User.all().annotate(total=Sum("api_token_call_count")).values("total")
        return int((result[0].get("total") if result else 0) or 0)

    @staticmethod
    def _storage_health() -> str:
        """按当前存储类型判断配置健康状态。"""

        provider = settings.STORAGE_PROVIDER.strip().lower() or "local"
        if provider == "local":
            return "ok"
        if provider == "qiniu":
            return "ok" if settings.QINIU_BUCKET else "unconfigured"
        if provider == "minio":
            return "ok" if settings.MINIO_ENDPOINT and settings.MINIO_BUCKET else "unconfigured"
        if provider == "cos":
            return "ok" if settings.COS_BUCKET and settings.COS_REGION else "unconfigured"
        return "unconfigured"
