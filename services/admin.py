from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, status
from tortoise.expressions import F, Q
from tortoise.functions import Sum

from core import redis as redis_module
from core.config import settings
from core.database import db_connected
from core.security import hash_password
from models.admin import AuditLog, ModelCallLog, ModelConfig, PointLedger, RechargeOrder
from models.paper import PaperOrder
from models.user import User
from schemas.admin import (
    AdminOrderDetailResponse,
    AdminOrderListItem,
    AdminOverviewResponse,
    AdminPointAdjustRequest,
    AdminRechargeOrderResponse,
    AdminRechargeReviewRequest,
    AdminResetPasswordRequest,
    AdminUserCreateRequest,
    AdminUserDetailResponse,
    AdminUserUpdateRequest,
    ModelConfigCreateRequest,
    ModelConfigResponse,
    ModelConfigUpdateRequest,
)
from schemas.common import PageResponse
from schemas.user import PointLedgerResponse, UserResponse
from services.user import RECHARGE_STATUS_TEXT


def mask_secret(value: str | None) -> str:
    """脱敏展示密钥或调用 token。"""

    if not value:
        return ""
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}****{value[-4:]}"


async def write_audit_log(
    *,
    operator: User | None,
    action: str,
    target_type: str,
    summary: str,
    target_id: str | int | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    ip_address: str | None = None,
) -> None:
    await AuditLog.create(
        operator=operator,
        action=action,
        target_type=target_type,
        target_id=str(target_id) if target_id is not None else None,
        summary=summary,
        before=before,
        after=after,
        ip_address=ip_address,
    )


class AdminService:
    """管理端业务服务。"""

    @staticmethod
    async def overview() -> AdminOverviewResponse:
        now = datetime.now(UTC)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        health = {
            "mysql": "ok" if db_connected else "degraded",
            "redis": "ok" if redis_module.redis_client is not None else "degraded",
            "storage": "ok" if settings.QINIU_BUCKET else "unconfigured",
            "model": "ok" if settings.DEEPSEEK_API_KEY else "unconfigured",
        }

        return AdminOverviewResponse(
            today_user_count=await User.filter(created_at__gte=today_start).count(),
            month_user_count=await User.filter(created_at__gte=month_start).count(),
            total_user_count=await User.all().count(),
            today_order_count=await PaperOrder.filter(created_at__gte=today_start).count(),
            month_order_count=await PaperOrder.filter(created_at__gte=month_start).count(),
            total_order_count=await PaperOrder.all().count(),
            today_spent_points=await AdminService._sum_paid_points(PaperOrder.filter(paid_at__gte=today_start)),
            month_spent_points=await AdminService._sum_paid_points(PaperOrder.filter(paid_at__gte=month_start)),
            total_spent_points=await AdminService._sum_paid_points(PaperOrder.all()),
            generating_order_count=await PaperOrder.filter(status="generating").count(),
            failed_order_count=await PaperOrder.filter(status="failed").count(),
            completed_order_count=await PaperOrder.filter(status="completed").count(),
            model_call_count=await ModelCallLog.all().count(),
            api_token_call_count=await AdminService._sum_api_token_calls(),
            health=health,
        )

    @staticmethod
    async def list_users(page: int, page_size: int, keyword: str | None = None) -> PageResponse[UserResponse]:
        query = User.all()
        if keyword:
            query = query.filter(
                Q(username__icontains=keyword) | Q(email__icontains=keyword) | Q(nickname__icontains=keyword)
            )
        total = await query.count()
        users = await query.order_by("-id").offset((page - 1) * page_size).limit(page_size)
        return PageResponse(
            total=total,
            page=page,
            page_size=page_size,
            items=[UserResponse.model_validate(item) for item in users],
        )

    @staticmethod
    async def create_user(data: AdminUserCreateRequest, operator: User, ip_address: str | None = None) -> UserResponse:
        if await User.filter(username=data.username).exists():
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="用户名已存在")
        if await User.filter(email=str(data.email)).exists():
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="邮箱已存在")
        user = await User.create(
            username=data.username,
            hashed_password=hash_password(data.password),
            email=str(data.email),
            nickname=data.nickname,
            avatar=data.avatar,
            points=data.initial_points,
            role=data.role,
        )
        if data.initial_points:
            await PointLedger.create(
                user=user,
                operator=operator,
                change_type="admin_grant",
                delta=data.initial_points,
                balance_after=user.points,
                reason="管理员创建账号初始积分",
            )
        await write_audit_log(
            operator=operator,
            action="create_user",
            target_type="user",
            target_id=user.id,
            summary=f"创建用户 {user.username}",
            after={"username": user.username, "role": user.role, "points": user.points},
            ip_address=ip_address,
        )
        return UserResponse.model_validate(user)

    @staticmethod
    async def get_user_detail(user_id: int) -> AdminUserDetailResponse:
        user = await AdminService._get_user(user_id)
        ledgers = await PointLedger.filter(user=user).order_by("-id").limit(20)
        return AdminUserDetailResponse(
            user=UserResponse.model_validate(user),
            point_ledgers=[PointLedgerResponse.model_validate(item) for item in ledgers],
            order_count=await PaperOrder.filter(user=user).count(),
            api_token={
                "has_token": bool(user.api_token),
                "masked_token": mask_secret(user.api_token),
                "created_at": user.api_token_created_at,
                "last_used_at": user.api_token_last_used_at,
                "call_count": user.api_token_call_count,
            },
        )

    @staticmethod
    async def update_user(
        user_id: int,
        data: AdminUserUpdateRequest,
        operator: User,
        ip_address: str | None = None,
    ) -> UserResponse:
        user = await AdminService._get_user(user_id)
        before = {
            "email": user.email,
            "nickname": user.nickname,
            "role": user.role,
            "is_disabled": user.is_disabled,
        }
        update_data = data.model_dump(exclude_unset=True)
        if "email" in update_data and update_data["email"] is not None:
            exists = await User.filter(email=str(update_data["email"])).exclude(id=user.id).exists()
            if exists:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="邮箱已存在")
            update_data["email"] = str(update_data["email"])
        if update_data:
            await user.update_from_dict(update_data).save()
        await write_audit_log(
            operator=operator,
            action="update_user",
            target_type="user",
            target_id=user.id,
            summary=f"更新用户 {user.username}",
            before=before,
            after=update_data,
            ip_address=ip_address,
        )
        return UserResponse.model_validate(user)

    @staticmethod
    async def reset_password(
        user_id: int,
        data: AdminResetPasswordRequest,
        operator: User,
        ip_address: str | None = None,
    ) -> None:
        user = await AdminService._get_user(user_id)
        user.hashed_password = hash_password(data.password)
        await user.save(update_fields=["hashed_password", "updated_at"])
        await write_audit_log(
            operator=operator,
            action="reset_password",
            target_type="user",
            target_id=user.id,
            summary=f"重置用户 {user.username} 密码",
            ip_address=ip_address,
        )

    @staticmethod
    async def adjust_points(
        user_id: int,
        data: AdminPointAdjustRequest,
        operator: User,
        ip_address: str | None = None,
    ) -> PointLedgerResponse:
        user = await AdminService._get_user(user_id)
        if data.delta == 0:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="积分变更不能为 0")
        if data.delta < 0 and user.points + data.delta < 0:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="扣减后积分不能为负数")
        await User.filter(id=user.id).update(points=F("points") + data.delta)
        await user.refresh_from_db()
        ledger = await PointLedger.create(
            user=user,
            operator=operator,
            change_type="admin_adjust",
            delta=data.delta,
            balance_after=user.points,
            reason=data.reason,
        )
        await write_audit_log(
            operator=operator,
            action="adjust_points",
            target_type="user",
            target_id=user.id,
            summary=f"调整用户 {user.username} 积分 {data.delta}",
            before={"points": user.points - data.delta},
            after={"points": user.points, "reason": data.reason},
            ip_address=ip_address,
        )
        return PointLedgerResponse.model_validate(ledger)

    @staticmethod
    async def list_recharge_orders(
        page: int,
        page_size: int,
        status_value: str | None = None,
        keyword: str | None = None,
    ) -> PageResponse[AdminRechargeOrderResponse]:
        query = RechargeOrder.all().select_related("user", "reviewer")
        if status_value:
            query = query.filter(status=status_value)
        if keyword:
            query = query.filter(Q(order_sn__icontains=keyword) | Q(user__username__icontains=keyword))
        total = await query.count()
        orders = await query.order_by("-id").offset((page - 1) * page_size).limit(page_size)
        return PageResponse(
            total=total,
            page=page,
            page_size=page_size,
            items=[AdminService._recharge_order_response(item) for item in orders],
        )

    @staticmethod
    async def review_recharge_order(
        order_id: int,
        data: AdminRechargeReviewRequest,
        operator: User,
        ip_address: str | None = None,
    ) -> AdminRechargeOrderResponse:
        order = await RechargeOrder.filter(id=order_id).select_related("user").first()
        if order is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="充值申请不存在")
        if order.status != "pending":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="充值申请已处理")

        now = datetime.now(UTC)
        order.status = data.status
        order.admin_remark = data.admin_remark
        order.reviewer_id = operator.id
        order.reviewed_at = now
        await order.save(update_fields=["status", "admin_remark", "reviewer_id", "reviewed_at", "updated_at"])

        if data.status == "approved":
            await User.filter(id=order.user_id).update(points=F("points") + order.points)
            user = await User.get(id=order.user_id)
            await PointLedger.create(
                user=user,
                operator=operator,
                change_type="recharge",
                delta=order.points,
                balance_after=user.points,
                reason=f"充值申请 {order.order_sn} 审核入账",
                metadata={"recharge_order_id": order.id, "admin_remark": data.admin_remark},
            )

        await write_audit_log(
            operator=operator,
            action="review_recharge",
            target_type="recharge_order",
            target_id=order.id,
            summary=f"审核充值申请 {order.order_sn}: {data.status}",
            after={"status": data.status, "points": order.points, "admin_remark": data.admin_remark},
            ip_address=ip_address,
        )
        return AdminService._recharge_order_response(order)

    @staticmethod
    async def list_orders(
        page: int,
        page_size: int,
        keyword: str | None = None,
        status_value: str | None = None,
        user_id: int | None = None,
    ) -> PageResponse[AdminOrderListItem]:
        query = PaperOrder.all().select_related("user")
        if keyword:
            query = query.filter(Q(order_sn__icontains=keyword) | Q(title__icontains=keyword))
        if status_value:
            query = query.filter(status=status_value)
        if user_id is not None:
            query = query.filter(user_id=user_id)
        total = await query.count()
        orders = await query.order_by("-id").offset((page - 1) * page_size).limit(page_size)
        return PageResponse(
            total=total,
            page=page,
            page_size=page_size,
            items=[AdminService._order_list_item(item) for item in orders],
        )

    @staticmethod
    async def get_order_detail(order_id: int) -> AdminOrderDetailResponse:
        order = await AdminService._get_order(order_id)
        ledgers = await PointLedger.filter(order=order).order_by("-id")
        return AdminOrderDetailResponse(
            order=AdminService._order_list_item(order),
            config_form=order.config_form if isinstance(order.config_form, dict) else None,
            outline_json=order.outline_json if isinstance(order.outline_json, list) else [],
            request_payload=order.outline_record.request_payload
            if isinstance(order.outline_record.request_payload, dict)
            else None,
            point_ledgers=[PointLedgerResponse.model_validate(item) for item in ledgers],
        )

    @staticmethod
    async def refund_order_points(
        order_id: int,
        operator: User,
        reason: str,
        ip_address: str | None = None,
    ) -> PaperOrder:
        order = await AdminService._get_order(order_id)
        refundable = order.paid_points - order.refunded_points
        if refundable <= 0:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="订单没有可退积分")
        await User.filter(id=order.user_id).update(points=F("points") + refundable)
        user = await User.get(id=order.user_id)
        now = datetime.now(UTC)
        order.refunded_points += refundable
        order.refunded_at = now
        order.status = "refunded"
        await order.save(update_fields=["refunded_points", "refunded_at", "status", "updated_at"])
        await PointLedger.create(
            user=user,
            operator=operator,
            order=order,
            change_type="order_refund",
            delta=refundable,
            balance_after=user.points,
            reason=reason,
        )
        await write_audit_log(
            operator=operator,
            action="refund_order",
            target_type="paper_order",
            target_id=order.id,
            summary=f"订单 {order.order_sn} 退回积分 {refundable}",
            after={"refunded_points": order.refunded_points, "reason": reason},
            ip_address=ip_address,
        )
        return order

    @staticmethod
    async def mark_order_failed(
        order_id: int,
        operator: User,
        reason: str,
        ip_address: str | None = None,
    ) -> PaperOrder:
        order = await AdminService._get_order(order_id)
        order.status = "failed"
        order.last_error = reason[:500]
        await order.save(update_fields=["status", "last_error", "updated_at"])
        await write_audit_log(
            operator=operator,
            action="mark_order_failed",
            target_type="paper_order",
            target_id=order.id,
            summary=f"标记订单 {order.order_sn} 失败",
            after={"reason": reason},
            ip_address=ip_address,
        )
        return order

    @staticmethod
    async def attach_order_file(
        order_id: int,
        operator: User,
        download_url: str,
        file_key: str | None,
        reason: str,
        ip_address: str | None = None,
    ) -> PaperOrder:
        order = await AdminService._get_order(order_id)
        order.status = "completed"
        order.download_url = download_url
        order.file_key = file_key or order.file_key
        order.completed_at = datetime.now(UTC)
        order.last_error = ""
        await order.save(
            update_fields=["status", "download_url", "file_key", "completed_at", "last_error", "updated_at"]
        )
        await write_audit_log(
            operator=operator,
            action="attach_order_file",
            target_type="paper_order",
            target_id=order.id,
            summary=f"人工补发订单 {order.order_sn} 下载链接",
            after={"download_url": download_url, "file_key": file_key, "reason": reason},
            ip_address=ip_address,
        )
        return order

    @staticmethod
    async def retry_order(order_id: int, operator: User, ip_address: str | None = None) -> PaperOrder:
        order = await AdminService._get_order(order_id)
        if order.paid_points <= order.refunded_points:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="订单未支付或已退款，不能重试")
        if order.status == "generating":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="订单正在生成中")
        order.status = "paid"
        order.last_error = ""
        await order.save(update_fields=["status", "last_error", "updated_at"])
        await write_audit_log(
            operator=operator,
            action="retry_order",
            target_type="paper_order",
            target_id=order.id,
            summary=f"重试订单 {order.order_sn}",
            ip_address=ip_address,
        )
        return order

    @staticmethod
    async def list_model_configs() -> list[ModelConfigResponse]:
        configs = await ModelConfig.all().order_by("config_type", "-is_default", "-id")
        return [AdminService._model_config_response(item) for item in configs]

    @staticmethod
    async def create_model_config(
        data: ModelConfigCreateRequest,
        operator: User,
        ip_address: str | None = None,
    ) -> ModelConfigResponse:
        if data.is_default:
            await ModelConfig.filter(config_type=data.config_type).update(is_default=False)
        config = await ModelConfig.create(**data.model_dump())
        await write_audit_log(
            operator=operator,
            action="create_model_config",
            target_type="model_config",
            target_id=config.id,
            summary=f"创建模型配置 {config.config_type}/{config.model_name}",
            after={"config_type": config.config_type, "provider": config.provider, "model_name": config.model_name},
            ip_address=ip_address,
        )
        return AdminService._model_config_response(config)

    @staticmethod
    async def update_model_config(
        config_id: int,
        data: ModelConfigUpdateRequest,
        operator: User,
        ip_address: str | None = None,
    ) -> ModelConfigResponse:
        config = await AdminService._get_model_config(config_id)
        before = AdminService._model_config_snapshot(config)
        update_data = data.model_dump(exclude_unset=True)
        next_type = str(update_data.get("config_type") or config.config_type)
        if update_data.get("is_default"):
            await ModelConfig.filter(config_type=next_type).exclude(id=config.id).update(is_default=False)
        if update_data:
            await config.update_from_dict(update_data).save()
        await write_audit_log(
            operator=operator,
            action="update_model_config",
            target_type="model_config",
            target_id=config.id,
            summary=f"更新模型配置 {config.config_type}/{config.model_name}",
            before=before,
            after=AdminService._model_config_snapshot(config),
            ip_address=ip_address,
        )
        return AdminService._model_config_response(config)

    @staticmethod
    async def delete_model_config(config_id: int, operator: User, ip_address: str | None = None) -> None:
        config = await AdminService._get_model_config(config_id)
        before = AdminService._model_config_snapshot(config)
        await config.delete()
        await write_audit_log(
            operator=operator,
            action="delete_model_config",
            target_type="model_config",
            target_id=config_id,
            summary=f"删除模型配置 {before['config_type']}/{before['model_name']}",
            before=before,
            ip_address=ip_address,
        )

    @staticmethod
    async def list_model_call_logs(page: int, page_size: int) -> PageResponse[dict[str, Any]]:
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

    @staticmethod
    async def _get_user(user_id: int) -> User:
        user = await User.filter(id=user_id).first()
        if user is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")
        return user

    @staticmethod
    async def _get_order(order_id: int) -> PaperOrder:
        order = await PaperOrder.filter(id=order_id).select_related("user", "outline_record").first()
        if order is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="订单不存在")
        return order

    @staticmethod
    async def _get_model_config(config_id: int) -> ModelConfig:
        config = await ModelConfig.filter(id=config_id).first()
        if config is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="模型配置不存在")
        return config

    @staticmethod
    async def _sum_paid_points(query: Any) -> int:
        result = await query.annotate(total=Sum("paid_points")).values("total")
        return int((result[0].get("total") if result else 0) or 0)

    @staticmethod
    async def _sum_api_token_calls() -> int:
        result = await User.all().annotate(total=Sum("api_token_call_count")).values("total")
        return int((result[0].get("total") if result else 0) or 0)

    @staticmethod
    def _order_list_item(order: PaperOrder) -> AdminOrderListItem:
        return AdminOrderListItem(
            id=order.id,
            order_sn=order.order_sn,
            user_id=order.user_id,
            username=order.user.username if order.user else "",
            title=order.title,
            status=order.status,
            cost_points=order.cost_points,
            paid_points=order.paid_points,
            refunded_points=order.refunded_points,
            task_id=order.task_id,
            file_key=order.file_key,
            download_url=order.download_url,
            last_error=order.last_error,
            created_at=order.created_at,
            paid_at=order.paid_at,
            completed_at=order.completed_at,
        )

    @staticmethod
    def _model_config_response(config: ModelConfig) -> ModelConfigResponse:
        return ModelConfigResponse(
            id=config.id,
            config_type=config.config_type,
            provider=config.provider,
            model_name=config.model_name,
            api_base_url=config.api_base_url,
            masked_api_key=mask_secret(config.api_key),
            temperature=config.temperature,
            max_tokens=config.max_tokens,
            timeout_seconds=config.timeout_seconds,
            is_enabled=config.is_enabled,
            is_default=config.is_default,
            remark=config.remark,
            created_at=config.created_at,
            updated_at=config.updated_at,
        )

    @staticmethod
    def _model_config_snapshot(config: ModelConfig) -> dict[str, Any]:
        return {
            "config_type": config.config_type,
            "provider": config.provider,
            "model_name": config.model_name,
            "api_base_url": config.api_base_url,
            "masked_api_key": mask_secret(config.api_key),
            "temperature": config.temperature,
            "max_tokens": config.max_tokens,
            "timeout_seconds": config.timeout_seconds,
            "is_enabled": config.is_enabled,
            "is_default": config.is_default,
            "remark": config.remark,
        }

    @staticmethod
    def _recharge_order_response(order: RechargeOrder) -> AdminRechargeOrderResponse:
        return AdminRechargeOrderResponse(
            id=order.id,
            order_sn=order.order_sn,
            points=order.points,
            amount=float(order.amount),
            pay_channel=order.pay_channel,
            status=order.status,
            status_text=RECHARGE_STATUS_TEXT.get(order.status, order.status),
            remark=order.remark,
            admin_remark=order.admin_remark,
            created_at=order.created_at,
            reviewed_at=order.reviewed_at,
            user_id=order.user_id,
            username=order.user.username if order.user else "",
            reviewer_id=order.reviewer_id,
        )
