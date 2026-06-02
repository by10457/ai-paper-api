"""管理端充值申请服务。"""

from fastapi import HTTPException, status
from tortoise import timezone
from tortoise.expressions import F, Q

from models.admin import PointLedger, RechargeOrder
from models.user import User
from schemas.admin import AdminRechargeOrderResponse, AdminRechargeReviewRequest
from schemas.common import PageResponse
from services.admin.audit import write_audit_log
from services.user import RECHARGE_STATUS_TEXT


class AdminRechargeService:
    """处理用户手动充值申请的查询和审核。"""

    @staticmethod
    async def list_recharge_orders(
        page: int,
        page_size: int,
        status_value: str | None = None,
        keyword: str | None = None,
    ) -> PageResponse[AdminRechargeOrderResponse]:
        """分页查询充值申请，支持状态和用户/单号关键字筛选。"""

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
            items=[AdminRechargeService._recharge_order_response(item) for item in orders],
        )

    @staticmethod
    async def review_recharge_order(
        order_id: int,
        data: AdminRechargeReviewRequest,
        operator: User,
        ip_address: str | None = None,
    ) -> AdminRechargeOrderResponse:
        """审核充值申请；通过时将积分入账并写入积分流水。"""

        order = await RechargeOrder.filter(id=order_id).select_related("user").first()
        if order is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="充值申请不存在")
        if order.status != "pending":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="充值申请已处理")

        now = timezone.now()
        order.status = data.status
        order.admin_remark = data.admin_remark
        order.reviewer_id = operator.id
        order.reviewed_at = now
        await order.save(update_fields=["status", "admin_remark", "reviewer_id", "reviewed_at", "updated_at"])

        if data.status == "approved":
            # 审核通过才增加用户积分；驳回只记录审核结果和审计日志。
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
        return AdminRechargeService._recharge_order_response(order)

    @staticmethod
    def _recharge_order_response(order: RechargeOrder) -> AdminRechargeOrderResponse:
        """转换为管理端充值申请响应结构。"""

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
