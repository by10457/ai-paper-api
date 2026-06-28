"""论文订单 API 流程编排。"""

import logging

from fastapi import HTTPException, status

from core.config import settings
from models.paper import PaperGenerationTask, PaperOrder
from models.user import User
from schemas.common import PageResponse
from schemas.thesis import (
    PaperOrderCreateRequest,
    PaperOrderCreateResponse,
    PaperOrderDetailResponse,
    PaperOrderDownloadUrlResponse,
    PaperOrderListItemResponse,
    PaperOrderPayRequest,
    PaperOrderPayResponse,
    PaperOrderStatusResponse,
    PaperOutlineCreateRequest,
    PaperOutlineRecordResponse,
    PaperPriceResponse,
)
from services.thesis.business.order_service import PaperOrderService
from services.thesis.generation import status_store
from services.thesis.generation.paper_queue import enqueue_generation_task
from services.thesis.generation.runtime_context import use_runtime_context
from services.thesis.generation.task_service import (
    load_generate_outline,
    run_generation_task,
)

logger = logging.getLogger(__name__)


def get_price_for_user(user: User) -> PaperPriceResponse:
    """返回当前论文生成价格和用户积分余额。"""

    return PaperPriceResponse(
        points=settings.PAPER_GENERATE_POINTS,
        amount=settings.PAPER_GENERATE_POINTS / 10,
        user_points=user.points,
    )


async def create_outline_record(user: User, req: PaperOutlineCreateRequest) -> PaperOutlineRecordResponse:
    """生成大纲并保存可下单的大纲记录。"""

    try:
        generate_outline = load_generate_outline()
        with use_runtime_context(user_id=user.id, stage="outline"):
            outline_data = await generate_outline(
                req.title,
                int(req.form_params.get("lengthnum") or 8000),
                str(req.form_params.get("codetype") or "否"),
                str(req.form_params.get("language") or "否"),
                req.three_level,
                req.about_msg,
            )
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"大纲生成失败: {exc}") from exc
    record = await PaperOrderService.create_outline_record(user, req, outline_data)
    return PaperOutlineRecordResponse(
        record_id=record.id,
        outline=outline_data.get("outline", []),
        abstract=str(outline_data.get("abstract", "")),
        keywords=str(outline_data.get("keywords", "")),
    )


async def create_order(
    user: User,
    req: PaperOrderCreateRequest,
    idempotency_key: str | None = None,
) -> PaperOrderCreateResponse:
    """基于用户确认的大纲创建待支付论文订单。"""

    order = await PaperOrderService.create_order(user, req, idempotency_key)
    return PaperOrderCreateResponse(
        order_sn=order.order_sn,
        amount=order.cost_points / 10,
        points=order.cost_points,
    )


async def pay_order(
    user: User,
    req: PaperOrderPayRequest,
) -> PaperOrderPayResponse:
    """完成积分支付，支付成功后由独立论文 worker 消费生成。"""

    order = await PaperOrderService.get_order(user, req.order_sn)
    should_enqueue = await PaperOrderService.pay_order(user, order)
    if should_enqueue:
        generation_task = await PaperOrderService.create_order_generation_task(order.id)
        await enqueue_generation_task(generation_task.id)
    return PaperOrderPayResponse(
        order_sn=order.order_sn,
        points=user.points,
        cost_points=order.cost_points,
    )


async def get_order_status(user: User, order_sn: str) -> PaperOrderStatusResponse:
    """查询论文订单状态，生成中订单会同步最新任务状态。"""

    order = await PaperOrderService.get_order(user, order_sn)
    order = await _refresh_generating_order(order)
    return _paper_order_status_response(order)


async def get_order_download_url(user: User, order_sn: str) -> PaperOrderDownloadUrlResponse:
    """获取已完成论文订单的下载链接。"""

    order = await PaperOrderService.get_order(user, order_sn)
    order = await _refresh_generating_order(order)
    download_url = _build_order_download_url(order)
    if order.status != "completed" or not download_url:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="论文尚未生成完成")
    return PaperOrderDownloadUrlResponse(
        order_sn=order.order_sn,
        download_url=download_url,
        file_key=order.file_key,
        storage_provider=order.storage_provider,
        local_file_key=order.local_file_key,
        local_download_url=_build_local_order_download_url(order),
    )


async def list_user_orders(user: User, page: int, page_size: int) -> PageResponse[PaperOrderListItemResponse]:
    """分页查询当前用户论文订单。"""

    query = PaperOrder.filter(user=user)
    total = await query.count()
    orders = await query.order_by("-id").offset((page - 1) * page_size).limit(page_size)
    return PageResponse(
        total=total,
        page=page,
        page_size=page_size,
        items=[_paper_order_list_item(order) for order in orders],
    )


async def get_user_order_detail(user: User, order_sn: str) -> PaperOrderDetailResponse:
    """查询当前用户论文订单详情。"""

    order = await PaperOrderService.get_order(user, order_sn)
    order = await _refresh_generating_order(order)
    item = _paper_order_list_item(order)
    generation_task = await _latest_generation_task(order.id)
    return PaperOrderDetailResponse(
        **item.model_dump(),
        config_form=order.config_form if isinstance(order.config_form, dict) else None,
        outline_json=order.outline_json if isinstance(order.outline_json, list) else [],
        task_id=order.task_id,
        task_stage=generation_task.current_stage if generation_task else None,
        task_progress=generation_task.progress if generation_task else 0,
        process_events=generation_task.process_events
        if generation_task and isinstance(generation_task.process_events, list)
        else [],
        process_metadata=generation_task.process_metadata
        if generation_task and isinstance(generation_task.process_metadata, dict)
        else None,
        result_summary=generation_task.result_summary
        if generation_task and isinstance(generation_task.result_summary, dict)
        else None,
        file_key=order.file_key,
        storage_provider=order.storage_provider,
        local_file_key=order.local_file_key,
        local_download_url=_build_local_order_download_url(order),
    )


async def run_paid_paper_order(order_id: int) -> None:
    """支付成功后的后台生成流程，失败时回写订单状态。"""

    try:
        generation_task = await PaperOrderService.create_order_generation_task(order_id)
        await run_generation_task(generation_task.id)
    except Exception as exc:  # noqa: BLE001
        logger.exception("论文订单后台生成失败")
        order = await PaperOrder.filter(id=order_id).first()
        if order is not None:
            order.status = "failed"
            order.last_error = str(exc)[:500]
            await order.save(update_fields=["status", "last_error", "updated_at"])


async def _refresh_generating_order(order: PaperOrder) -> PaperOrder:
    if order.task_id and order.status in {"generating", "paid"}:
        status_data = await status_store.read_status_async(order.task_id)
        return await PaperOrderService.mark_from_task_status(order, status_data)
    return order


def _paper_order_status_response(order: PaperOrder) -> PaperOrderStatusResponse:
    status_data = status_store.read_status(order.task_id) if order.task_id else None
    is_paid = 1 if order.status in {"paid", "generating", "completed", "failed"} else 0
    has_file = 1 if order.status == "completed" else 0
    return PaperOrderStatusResponse(
        order_sn=order.order_sn,
        status=order.status,
        is_paid=is_paid,
        has_file=has_file,
        task_id=order.task_id,
        file_key=order.file_key,
        storage_provider=order.storage_provider,
        local_file_key=order.local_file_key,
        local_download_url=_build_local_order_download_url(order),
        download_url=_build_order_download_url(order),
        error_msg=order.last_error,
        message=str(status_data.get("message") or "") if status_data else order.last_error,
        stage=str(status_data.get("stage") or "") if status_data else None,
        progress=int(status_data.get("progress") or (100 if order.status == "completed" else 0)) if status_data else 0,
        events=status_data.get("events", []) if status_data else [],
    )


async def _latest_generation_task(order_id: int) -> PaperGenerationTask | None:
    return await PaperGenerationTask.filter(order_id=order_id).order_by("-id").first()


def _paper_order_list_item(order: PaperOrder) -> PaperOrderListItemResponse:
    return PaperOrderListItemResponse(
        id=order.id,
        order_sn=order.order_sn,
        title=order.title,
        status=order.status,
        cost_points=order.cost_points,
        paid_points=order.paid_points,
        refunded_points=order.refunded_points,
        has_file=1 if order.status == "completed" else 0,
        download_url=None,
        error_msg=order.last_error,
        created_at=order.created_at.isoformat(),
        paid_at=order.paid_at.isoformat() if order.paid_at else None,
        completed_at=order.completed_at.isoformat() if order.completed_at else None,
    )


def _build_order_download_url(order: PaperOrder) -> str | None:
    if order.status != "completed":
        return None
    if order.storage_provider == "manual" and order.download_url:
        return order.download_url
    from services.thesis.storage.document_storage import build_download_url

    return build_download_url(order.storage_provider, order.file_key, order.local_file_key) or order.download_url


def _build_local_order_download_url(order: PaperOrder) -> str | None:
    if order.status != "completed" or not order.local_file_key:
        return None
    from services.thesis.storage.document_storage import build_local_download_url

    return build_local_download_url(order.local_file_key)
