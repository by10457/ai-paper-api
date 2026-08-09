"""通用学术材料的订单、任务和查询工作流。"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status
from pydantic import BaseModel

from core.config import settings
from models.paper import PaperGenerationTask, PaperOrder
from models.user import User
from schemas.common import PageResponse
from schemas.writing import (
    WritingDocumentType,
    WritingOrderDetail,
    WritingOrderListItem,
    WritingProductResponse,
    WritingProductsResponse,
    WritingSubmitResponse,
    WritingTaskResponse,
)
from services.thesis.business.order_service import PaperOrderService
from services.thesis.generation import status_store
from services.thesis.generation.paper_queue import enqueue_generation_task
from services.thesis.generation.progress import publish_progress
from services.thesis.storage.document_storage import build_download_url

PRODUCTS: dict[str, tuple[str, int, int | None, int | None, int | None]] = {
    "proposal_report": ("开题报告", settings.PROPOSAL_REPORT_POINTS, 4000, 15, 8),
    "literature_review": ("文献综述", settings.LITERATURE_REVIEW_POINTS, 6000, 20, 12),
    "task_book": ("任务书", settings.TASK_BOOK_POINTS, None, None, None),
}


def list_products(user: User) -> WritingProductsResponse:
    """返回产品价格、默认生成规则和当前用户余额。"""

    return WritingProductsResponse(
        user_points=user.points,
        products=[
            WritingProductResponse(
                document_type=document_type,  # type: ignore[arg-type]
                name=value[0],
                points=value[1],
                default_word_count=value[2],
                default_reference_count=value[3],
                minimum_reference_count=value[4],
            )
            for document_type, value in PRODUCTS.items()
        ],
    )


async def submit_request(
    user: User,
    document_type: WritingDocumentType,
    request: BaseModel,
    idempotency_key: str | None,
) -> WritingSubmitResponse:
    """原子扣费、创建订单任务并加入现有 Redis worker 队列。"""

    request_payload = request.model_dump(mode="json")
    task_id = PaperOrderService._generate_task_id()
    points = PRODUCTS[document_type][1]
    generation_task, should_start = await PaperOrderService.create_direct_generate_task(
        user,
        task_id=task_id,
        title=str(request_payload["title"]),
        request_payload=request_payload,
        idempotency_key=idempotency_key,
        document_type=document_type,
        cost_points=points,
    )
    if await status_store.read_status_async(generation_task.task_id) is None:
        await publish_progress(generation_task.task_id, "queued", f"{PRODUCTS[document_type][0]}任务已进入队列", progress=2)
    if should_start:
        await enqueue_generation_task(generation_task.id)
    order = await PaperOrder.filter(id=generation_task.order_id).first()
    if order is None:
        raise RuntimeError("写作订单创建失败")
    return WritingSubmitResponse(
        task_id=generation_task.task_id,
        order_sn=order.order_sn,
        document_type=document_type,
        charged_points=order.paid_points,
    )


async def get_task(user: User, task_id: str) -> WritingTaskResponse:
    """查询当前用户拥有的写作任务。"""

    generation_task = await _owned_task(user, task_id)
    order = await PaperOrder.filter(id=generation_task.order_id).first()
    if order is None:
        raise HTTPException(status_code=404, detail="写作订单不存在")
    status_data = await status_store.read_status_async(task_id) or {}
    return _task_response(generation_task, order, status_data)


async def list_orders(
    user: User,
    page: int,
    page_size: int,
) -> PageResponse[WritingOrderListItem]:
    """分页查询当前用户的三类学术材料订单。"""

    page = max(page, 1)
    page_size = min(max(page_size, 1), 50)
    query = PaperOrder.filter(user_id=user.id).exclude(document_type="thesis")
    total = await query.count()
    orders = await query.order_by("-id").offset((page - 1) * page_size).limit(page_size)
    return PageResponse(
        total=total,
        page=page,
        page_size=page_size,
        items=[_order_list_item(order) for order in orders],
    )


async def get_order(user: User, order_sn: str) -> WritingOrderDetail:
    """查询写作订单、任务进度和结构化结果。"""

    order = await PaperOrder.filter(user_id=user.id, order_sn=order_sn).exclude(document_type="thesis").first()
    if order is None:
        raise HTTPException(status_code=404, detail="写作订单不存在")
    task = await PaperGenerationTask.filter(order_id=order.id).order_by("-id").first()
    status_data = await status_store.read_status_async(task.task_id) if task else {}
    item = _order_list_item(order)
    return WritingOrderDetail(
        **item.model_dump(),
        request=order.config_form if isinstance(order.config_form, dict) else {},
        result=task.result_data if task and isinstance(task.result_data, dict) else None,
        stage=str((status_data or {}).get("stage") or (task.current_stage if task else "") or ""),
        progress=int((status_data or {}).get("progress") or (task.progress if task else 0) or 0),
        error_message=order.last_error,
        download_url=build_download_url(order.storage_provider, order.file_key, order.local_file_key),
    )


async def _owned_task(user: User, task_id: str) -> PaperGenerationTask:
    task = await PaperGenerationTask.filter(task_id=task_id).first()
    if task is None or (task.user_id != user.id and user.role != "admin") or task.document_type == "thesis":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="写作任务不存在")
    return task


def _task_response(
    task: PaperGenerationTask,
    order: PaperOrder,
    status_data: dict[str, Any],
) -> WritingTaskResponse:
    if task.status == "completed":
        task_status = "completed"
    elif task.status == "failed" or order.status == "failed":
        task_status = "failed"
    elif task.status == "paid":
        task_status = "queued"
    else:
        task_status = "generating"
    return WritingTaskResponse(
        task_id=task.task_id,
        order_sn=order.order_sn,
        document_type=task.document_type,  # type: ignore[arg-type]
        title=task.title,
        status=task_status,  # type: ignore[arg-type]
        stage=str(status_data.get("stage") or task.current_stage or ""),
        progress=int(status_data.get("progress") or task.progress or 0),
        message=str(status_data.get("message") or task.last_error or ""),
        charged_points=order.paid_points,
        refunded_points=order.refunded_points,
        request=order.config_form if isinstance(order.config_form, dict) else {},
        result=task.result_data if isinstance(task.result_data, dict) else None,
        download_url=build_download_url(order.storage_provider, order.file_key, order.local_file_key),
        created_at=task.created_at.isoformat(),
        completed_at=task.completed_at.isoformat() if task.completed_at else None,
    )


def _order_list_item(order: PaperOrder) -> WritingOrderListItem:
    return WritingOrderListItem(
        order_sn=order.order_sn,
        task_id=order.task_id,
        document_type=order.document_type,  # type: ignore[arg-type]
        title=order.title,
        status=order.status,
        cost_points=order.cost_points,
        refunded_points=order.refunded_points,
        created_at=order.created_at.isoformat(),
        completed_at=order.completed_at.isoformat() if order.completed_at else None,
    )


__all__ = ["get_order", "get_task", "list_orders", "list_products", "submit_request"]

