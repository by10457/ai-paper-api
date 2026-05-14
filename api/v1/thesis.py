"""论文生成接口路由。"""

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi import Path as FastApiPath
from fastapi.responses import FileResponse

from api.dependencies.api_token import get_api_token_or_jwt_user
from models.user import User
from schemas.common import PageResponse, Response
from schemas.thesis import (
    GenerateRequest,
    GenerateSubmitResponse,
    OutlineRequest,
    OutlineResponse,
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
    TaskStatusResponse,
)
from services.thesis import generation_task, order_workflow

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/thesis", tags=["论文生成"])


@router.post("/outline", response_model=OutlineResponse)
async def create_outline(req: OutlineRequest) -> OutlineResponse:
    """根据标题生成论文大纲。"""

    try:
        return await generation_task.generate_outline_for_request(req)
    except RuntimeError as exc:
        logger.exception("大纲生成失败")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/generate", response_model=GenerateSubmitResponse)
async def generate_document(
    req: GenerateRequest,
    background_tasks: BackgroundTasks,
) -> GenerateSubmitResponse:
    """提交论文生成任务并立即返回 task_id。"""

    return generation_task.submit_generate_request(req, background_tasks)


@router.get("/status/{task_id}", response_model=TaskStatusResponse)
async def get_task_status(
    task_id: str = FastApiPath(..., pattern=r"^[a-zA-Z0-9_-]+$"),
) -> TaskStatusResponse:
    """查询任务状态。"""

    return generation_task.get_task_status(task_id)


@router.get("/download/{task_id}")
async def download_document(
    task_id: str = FastApiPath(..., pattern=r"^[a-zA-Z0-9_-]+$"),
) -> FileResponse:
    """下载生成的 Word 文档。"""

    path_obj = generation_task.get_download_path(task_id)
    return FileResponse(
        path=str(path_obj),
        media_type=("application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
        filename=path_obj.name,
    )


@router.get("/price", response_model=Response[PaperPriceResponse], summary="查询论文生成价格")
async def get_paper_price(current_user: User = Depends(get_api_token_or_jwt_user)) -> Response[PaperPriceResponse]:
    """查询论文生成价格和用户积分余额。"""

    return Response.ok(data=order_workflow.get_price_for_user(current_user))


@router.post("/outlines", response_model=Response[PaperOutlineRecordResponse], summary="生成论文大纲并保存记录")
async def create_paper_outline_record(
    req: PaperOutlineCreateRequest,
    current_user: User = Depends(get_api_token_or_jwt_user),
) -> Response[PaperOutlineRecordResponse]:
    """生成论文大纲并保存为可下单记录。"""

    try:
        data = await order_workflow.create_outline_record(current_user, req)
    except RuntimeError as exc:
        logger.exception("大纲生成失败")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return Response.ok(data=data)


@router.post("/orders", response_model=Response[PaperOrderCreateResponse], summary="创建论文订单")
async def create_paper_order(
    req: PaperOrderCreateRequest,
    current_user: User = Depends(get_api_token_or_jwt_user),
) -> Response[PaperOrderCreateResponse]:
    """创建待支付论文订单。"""

    return Response.ok(data=await order_workflow.create_order(current_user, req))


@router.post("/orders/pay", response_model=Response[PaperOrderPayResponse], summary="论文订单积分支付")
async def pay_paper_order(
    req: PaperOrderPayRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_api_token_or_jwt_user),
) -> Response[PaperOrderPayResponse]:
    """论文订单积分支付。"""

    data = await order_workflow.pay_order(current_user, req, background_tasks)
    return Response.ok(data=data)


@router.get("/orders/status", response_model=Response[PaperOrderStatusResponse], summary="查询论文订单状态")
async def check_paper_order_status(
    order_sn: str,
    current_user: User = Depends(get_api_token_or_jwt_user),
) -> Response[PaperOrderStatusResponse]:
    """查询论文订单状态。"""

    return Response.ok(data=await order_workflow.get_order_status(current_user, order_sn))


@router.get(
    "/orders/download-url",
    response_model=Response[PaperOrderDownloadUrlResponse],
    summary="获取论文下载链接",
)
async def get_paper_order_download_url(
    order_sn: str,
    current_user: User = Depends(get_api_token_or_jwt_user),
) -> Response[PaperOrderDownloadUrlResponse]:
    """获取已完成论文订单的下载链接。"""

    return Response.ok(data=await order_workflow.get_order_download_url(current_user, order_sn))


@router.get(
    "/orders", response_model=Response[PageResponse[PaperOrderListItemResponse]], summary="分页查询当前用户论文订单"
)
async def list_my_paper_orders(
    page: int = 1,
    page_size: int = 10,
    current_user: User = Depends(get_api_token_or_jwt_user),
) -> Response[PageResponse[PaperOrderListItemResponse]]:
    """分页查询当前用户论文订单。"""

    return Response.ok(data=await order_workflow.list_user_orders(current_user, page, page_size))


@router.get(
    "/orders/detail",
    response_model=Response[PaperOrderDetailResponse],
    summary="查询当前用户论文订单详情",
)
async def get_my_paper_order_detail(
    order_sn: str,
    current_user: User = Depends(get_api_token_or_jwt_user),
) -> Response[PaperOrderDetailResponse]:
    """查询当前用户论文订单详情。"""

    return Response.ok(data=await order_workflow.get_user_order_detail(current_user, order_sn))
