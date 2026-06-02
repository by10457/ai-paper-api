"""管理端论文订单服务。"""

from fastapi import HTTPException, status
from tortoise import timezone
from tortoise.expressions import F, Q

from models.admin import PointLedger
from models.paper import PaperOrder
from models.user import User
from schemas.admin import AdminOrderDetailResponse, AdminOrderListItem
from schemas.common import PageResponse
from schemas.user import PointLedgerResponse
from services.admin.audit import write_audit_log
from services.admin.helpers import get_order_or_404


class AdminOrderService:
    """处理论文订单查询、退款、重试和人工补发。"""

    @staticmethod
    async def list_orders(
        page: int,
        page_size: int,
        keyword: str | None = None,
        status_value: str | None = None,
        user_id: int | None = None,
    ) -> PageResponse[AdminOrderListItem]:
        """分页查询论文订单，支持按关键字、状态和用户筛选。"""

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
            items=[AdminOrderService._order_list_item(item) for item in orders],
        )

    @staticmethod
    async def get_order_detail(order_id: int) -> AdminOrderDetailResponse:
        """查询订单详情，包含配置快照、大纲和积分流水。"""

        order = await get_order_or_404(order_id)
        ledgers = await PointLedger.filter(order=order).order_by("-id")
        return AdminOrderDetailResponse(
            order=AdminOrderService._order_list_item(order),
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
        """退回订单剩余可退积分，并记录积分流水和审计日志。"""

        order = await get_order_or_404(order_id)
        refundable = order.paid_points - order.refunded_points
        if refundable <= 0:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="订单没有可退积分")
        # 先原子更新用户积分，再读取新余额写入流水，保证 balance_after 与数据库一致。
        await User.filter(id=order.user_id).update(points=F("points") + refundable)
        user = await User.get(id=order.user_id)
        now = timezone.now()
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
        """将订单标记为失败，保留最近一次失败原因。"""

        order = await get_order_or_404(order_id)
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
        """人工补发订单下载链接，并将订单置为完成。"""

        order = await get_order_or_404(order_id)
        order.status = "completed"
        order.download_url = download_url
        order.file_key = file_key or order.file_key
        order.completed_at = timezone.now()
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
        """将可重试订单退回已支付状态，等待生成流程重新调度。"""

        order = await get_order_or_404(order_id)
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
    def _order_list_item(order: PaperOrder) -> AdminOrderListItem:
        """转换为管理端订单列表项响应结构。"""

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
