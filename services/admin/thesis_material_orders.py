"""管理端论文材料订单只读查询服务。"""

from fastapi import HTTPException, status
from tortoise.expressions import Q

from models.paper_material import ThesisMaterialGenerationTask, ThesisMaterialOrder
from schemas.admin import AdminThesisMaterialOrderDetailResponse, AdminThesisMaterialOrderListItem
from schemas.common import PageResponse


class AdminThesisMaterialOrderService:
    """查询开题报告、文献综述和任务书订单。"""

    @staticmethod
    async def list_thesis_material_orders(
        page: int,
        page_size: int,
        keyword: str | None = None,
        status_value: str | None = None,
        document_type: str | None = None,
    ) -> PageResponse[AdminThesisMaterialOrderListItem]:
        query = ThesisMaterialOrder.all().select_related("user")
        if keyword:
            query = query.filter(Q(order_sn__icontains=keyword) | Q(title__icontains=keyword))
        if status_value:
            query = query.filter(status=status_value)
        if document_type:
            query = query.filter(document_type=document_type)
        total = await query.count()
        orders = await query.order_by("-id").offset((page - 1) * page_size).limit(page_size)
        items: list[AdminThesisMaterialOrderListItem] = []
        for order in orders:
            task = await ThesisMaterialGenerationTask.filter(order_id=order.id).order_by("-id").first()
            items.append(AdminThesisMaterialOrderService._list_item(order, task))
        return PageResponse(total=total, page=page, page_size=page_size, items=items)

    @staticmethod
    async def get_thesis_material_order_detail(order_id: int) -> AdminThesisMaterialOrderDetailResponse:
        order = await ThesisMaterialOrder.filter(id=order_id).select_related("user").first()
        if order is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="论文材料订单不存在")
        task = await ThesisMaterialGenerationTask.filter(order_id=order.id).order_by("-id").first()
        return AdminThesisMaterialOrderDetailResponse(
            order=AdminThesisMaterialOrderService._list_item(order, task),
            request_payload=order.request_payload if isinstance(order.request_payload, dict) else {},
            result_data=task.result_data if task and isinstance(task.result_data, dict) else None,
            storage_provider=order.storage_provider,
            file_key=order.file_key,
            local_file_key=order.local_file_key,
            download_url=order.download_url,
        )

    @staticmethod
    def _list_item(
        order: ThesisMaterialOrder,
        task: ThesisMaterialGenerationTask | None,
    ) -> AdminThesisMaterialOrderListItem:
        return AdminThesisMaterialOrderListItem(
            id=order.id,
            order_sn=order.order_sn,
            user_id=order.user_id,
            username=order.user.username if order.user else "",
            document_type=order.document_type,
            title=order.title,
            status=order.status,
            cost_points=order.cost_points,
            paid_points=order.paid_points,
            refunded_points=order.refunded_points,
            task_id=order.task_id,
            stage=task.current_stage if task else None,
            progress=task.progress if task else 0,
            last_error=order.last_error,
            created_at=order.created_at,
            completed_at=order.completed_at,
        )
