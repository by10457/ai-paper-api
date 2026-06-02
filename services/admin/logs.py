"""管理端日志查询服务。"""

from __future__ import annotations

from typing import Any

from models.admin import AuditLog, ModelCallLog
from schemas.common import PageResponse


class AdminLogService:
    """查询模型调用日志和管理员审计日志。"""

    @staticmethod
    async def list_model_call_logs(page: int, page_size: int) -> PageResponse[dict[str, Any]]:
        """分页查询大模型调用日志，保留外键 ID 便于前端关联详情。"""

        query = ModelCallLog.all()
        total = await query.count()
        logs = await query.order_by("-id").offset((page - 1) * page_size).limit(page_size)
        return PageResponse(
            total=total,
            page=page,
            page_size=page_size,
            items=[
                {
                    "id": item.id,
                    "user_id": item.user_id,
                    "order_id": item.order_id,
                    "model_config_id": item.model_config_id,
                    "config_type": item.config_type,
                    "provider": item.provider,
                    "model_name": item.model_name,
                    "input_tokens": item.input_tokens,
                    "output_tokens": item.output_tokens,
                    "latency_ms": item.latency_ms,
                    "status": item.status,
                    "error_message": item.error_message,
                    "created_at": item.created_at,
                }
                for item in logs
            ],
        )

    @staticmethod
    async def list_audit_logs(page: int, page_size: int) -> PageResponse[dict[str, Any]]:
        """分页查询管理员操作审计日志。"""

        query = AuditLog.all()
        total = await query.count()
        logs = await query.order_by("-id").offset((page - 1) * page_size).limit(page_size)
        return PageResponse(
            total=total,
            page=page,
            page_size=page_size,
            items=[
                {
                    "id": item.id,
                    "operator_id": item.operator_id,
                    "action": item.action,
                    "target_type": item.target_type,
                    "target_id": item.target_id,
                    "summary": item.summary,
                    "ip_address": item.ip_address,
                    "created_at": item.created_at,
                }
                for item in logs
            ],
        )
