"""论文与论文材料订单的统一查询服务。"""

from __future__ import annotations

from datetime import datetime
from typing import cast

from models.paper import PaperOrder
from models.paper_material import ThesisMaterialOrder
from models.user import User
from schemas.common import PageResponse
from schemas.thesis import UnifiedOrderDocumentType, UnifiedOrderListItemResponse


# 将论文订单转换为统一列表项。
def _paper_order_item(order: PaperOrder) -> UnifiedOrderListItemResponse:
    """将论文订单转换为统一列表项。

    Args:
        order: 论文订单模型。

    Returns:
        统一订单列表项。
    """

    return UnifiedOrderListItemResponse(
        order_sn=order.order_sn,
        document_type="thesis",
        title=order.title,
        status=order.status,
        paid_points=order.paid_points,
        refunded_points=order.refunded_points,
        has_file=1 if order.file_key or order.local_file_key or order.download_url else 0,
        error_message=order.last_error,
        created_at=order.created_at.isoformat(),
        completed_at=order.completed_at.isoformat() if order.completed_at else None,
    )


# 将论文材料订单转换为统一列表项。
def _material_order_item(order: ThesisMaterialOrder) -> UnifiedOrderListItemResponse:
    """将论文材料订单转换为统一列表项。

    Args:
        order: 论文材料订单模型。

    Returns:
        统一订单列表项。
    """

    return UnifiedOrderListItemResponse(
        order_sn=order.order_sn,
        document_type=cast(UnifiedOrderDocumentType, order.document_type),
        title=order.title,
        status=order.status,
        paid_points=order.paid_points,
        refunded_points=order.refunded_points,
        has_file=1 if order.file_key or order.local_file_key or order.download_url else 0,
        error_message=order.last_error,
        created_at=order.created_at.isoformat(),
        completed_at=order.completed_at.isoformat() if order.completed_at else None,
    )


# 合并两类订单候选记录并按创建时间完成统一分页。
def _merge_order_candidates(
    paper_orders: list[PaperOrder],
    material_orders: list[ThesisMaterialOrder],
    page: int,
    page_size: int,
    total: int,
) -> PageResponse[UnifiedOrderListItemResponse]:
    """合并两类订单候选记录并按创建时间完成统一分页。

    Args:
        paper_orders: 当前页所需的论文订单候选记录。
        material_orders: 当前页所需的论文材料订单候选记录。
        page: 当前页码。
        page_size: 每页数量。
        total: 两类订单总数。

    Returns:
        统一分页结果。
    """

    candidates: list[tuple[datetime, int, UnifiedOrderListItemResponse]] = [
        (order.created_at, order.id, _paper_order_item(order)) for order in paper_orders
    ]
    candidates.extend((order.created_at, order.id, _material_order_item(order)) for order in material_orders)
    candidates.sort(key=lambda candidate: (candidate[0], candidate[1]), reverse=True)
    offset = (page - 1) * page_size
    items = [candidate[2] for candidate in candidates[offset : offset + page_size]]
    return PageResponse(
        total=total,
        page=page,
        page_size=page_size,
        items=items,
    )


# 分页查询当前用户的论文和论文材料订单。
async def list_unified_orders(
    user: User,
    page: int,
    page_size: int,
) -> PageResponse[UnifiedOrderListItemResponse]:
    """分页查询当前用户的论文和论文材料订单。

    Args:
        user: 当前认证用户。
        page: 当前页码。
        page_size: 每页数量。

    Returns:
        按创建时间倒序排列的统一订单分页结果。
    """

    page = max(page, 1)
    page_size = min(max(page_size, 1), 50)
    candidate_limit = page * page_size
    paper_query = PaperOrder.filter(user_id=user.id)
    material_query = ThesisMaterialOrder.filter(user_id=user.id)
    paper_total = await paper_query.count()
    material_total = await material_query.count()
    paper_orders = await paper_query.order_by("-created_at", "-id").limit(candidate_limit)
    material_orders = await material_query.order_by("-created_at", "-id").limit(candidate_limit)
    return _merge_order_candidates(
        paper_orders,
        material_orders,
        page,
        page_size,
        paper_total + material_total,
    )


__all__ = ["list_unified_orders"]
