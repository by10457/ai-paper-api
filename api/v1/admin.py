from fastapi import APIRouter, BackgroundTasks, Depends, Request

from api.dependencies.auth import get_current_admin_user
from models.paper import PaperOrder
from models.user import User
from schemas.admin import (
    AdminOrderDetailResponse,
    AdminOrderFailRequest,
    AdminOrderListItem,
    AdminOrderManualFileRequest,
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
from schemas.common import PageResponse, Response
from schemas.thesis import PaperOrderStatusResponse
from schemas.user import PointLedgerResponse, UserResponse
from services.admin import AdminService
from services.thesis.order_workflow import run_paid_paper_order

router = APIRouter(prefix="/admin", tags=["管理后台"])


def _client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


def _order_status_response(order: PaperOrder) -> PaperOrderStatusResponse:
    return PaperOrderStatusResponse(
        order_sn=order.order_sn,
        status=order.status,
        is_paid=1 if order.paid_points > order.refunded_points else 0,
        has_file=1 if order.status == "completed" else 0,
        task_id=order.task_id,
        file_key=order.file_key,
        download_url=order.download_url,
        error_msg=order.last_error,
    )


@router.get("/overview", response_model=Response[AdminOverviewResponse], summary="管理员工作台总览")
async def get_overview(_: User = Depends(get_current_admin_user)) -> Response[AdminOverviewResponse]:
    return Response.ok(data=await AdminService.overview())


@router.get("/users", response_model=Response[PageResponse[UserResponse]], summary="分页查询用户")
async def list_users(
    page: int = 1,
    page_size: int = 10,
    keyword: str | None = None,
    _: User = Depends(get_current_admin_user),
) -> Response[PageResponse[UserResponse]]:
    return Response.ok(data=await AdminService.list_users(page, page_size, keyword))


@router.post("/users", response_model=Response[UserResponse], summary="创建用户账号")
async def create_user(
    data: AdminUserCreateRequest,
    request: Request,
    current_admin: User = Depends(get_current_admin_user),
) -> Response[UserResponse]:
    return Response.ok(data=await AdminService.create_user(data, current_admin, _client_ip(request)))


@router.get("/users/{user_id}", response_model=Response[AdminUserDetailResponse], summary="查询用户详情")
async def get_user_detail(
    user_id: int,
    _: User = Depends(get_current_admin_user),
) -> Response[AdminUserDetailResponse]:
    return Response.ok(data=await AdminService.get_user_detail(user_id))


@router.patch("/users/{user_id}", response_model=Response[UserResponse], summary="更新用户资料/角色/状态")
async def update_user(
    user_id: int,
    data: AdminUserUpdateRequest,
    request: Request,
    current_admin: User = Depends(get_current_admin_user),
) -> Response[UserResponse]:
    return Response.ok(data=await AdminService.update_user(user_id, data, current_admin, _client_ip(request)))


@router.post("/users/{user_id}/password", response_model=Response[None], summary="重置用户密码")
async def reset_password(
    user_id: int,
    data: AdminResetPasswordRequest,
    request: Request,
    current_admin: User = Depends(get_current_admin_user),
) -> Response[None]:
    await AdminService.reset_password(user_id, data, current_admin, _client_ip(request))
    return Response.ok()


@router.post("/users/{user_id}/points", response_model=Response[PointLedgerResponse], summary="调整用户积分")
async def adjust_points(
    user_id: int,
    data: AdminPointAdjustRequest,
    request: Request,
    current_admin: User = Depends(get_current_admin_user),
) -> Response[PointLedgerResponse]:
    return Response.ok(data=await AdminService.adjust_points(user_id, data, current_admin, _client_ip(request)))


@router.get(
    "/recharge-orders",
    response_model=Response[PageResponse[AdminRechargeOrderResponse]],
    summary="分页查询积分充值申请",
)
async def list_recharge_orders(
    page: int = 1,
    page_size: int = 10,
    status: str | None = None,
    keyword: str | None = None,
    _: User = Depends(get_current_admin_user),
) -> Response[PageResponse[AdminRechargeOrderResponse]]:
    return Response.ok(data=await AdminService.list_recharge_orders(page, page_size, status, keyword))


@router.post(
    "/recharge-orders/{order_id}/review",
    response_model=Response[AdminRechargeOrderResponse],
    summary="审核积分充值申请",
)
async def review_recharge_order(
    order_id: int,
    data: AdminRechargeReviewRequest,
    request: Request,
    current_admin: User = Depends(get_current_admin_user),
) -> Response[AdminRechargeOrderResponse]:
    return Response.ok(data=await AdminService.review_recharge_order(order_id, data, current_admin, _client_ip(request)))


@router.get("/orders", response_model=Response[PageResponse[AdminOrderListItem]], summary="分页查询全量订单")
async def list_orders(
    page: int = 1,
    page_size: int = 10,
    keyword: str | None = None,
    status: str | None = None,
    user_id: int | None = None,
    _: User = Depends(get_current_admin_user),
) -> Response[PageResponse[AdminOrderListItem]]:
    return Response.ok(data=await AdminService.list_orders(page, page_size, keyword, status, user_id))


@router.get("/orders/{order_id}", response_model=Response[AdminOrderDetailResponse], summary="查询订单详情")
async def get_order_detail(
    order_id: int,
    _: User = Depends(get_current_admin_user),
) -> Response[AdminOrderDetailResponse]:
    return Response.ok(data=await AdminService.get_order_detail(order_id))


@router.post("/orders/{order_id}/retry", response_model=Response[PaperOrderStatusResponse], summary="重试生成订单")
async def retry_order(
    order_id: int,
    request: Request,
    background_tasks: BackgroundTasks,
    current_admin: User = Depends(get_current_admin_user),
) -> Response[PaperOrderStatusResponse]:
    order = await AdminService.retry_order(order_id, current_admin, _client_ip(request))
    background_tasks.add_task(run_paid_paper_order, order.id)
    return Response.ok(data=_order_status_response(order))


@router.post("/orders/{order_id}/refund", response_model=Response[PaperOrderStatusResponse], summary="退回订单积分")
async def refund_order(
    order_id: int,
    data: AdminOrderFailRequest,
    request: Request,
    current_admin: User = Depends(get_current_admin_user),
) -> Response[PaperOrderStatusResponse]:
    order = await AdminService.refund_order_points(order_id, current_admin, data.reason, _client_ip(request))
    return Response.ok(data=_order_status_response(order))


@router.post("/orders/{order_id}/fail", response_model=Response[PaperOrderStatusResponse], summary="标记订单失败")
async def mark_order_failed(
    order_id: int,
    data: AdminOrderFailRequest,
    request: Request,
    current_admin: User = Depends(get_current_admin_user),
) -> Response[PaperOrderStatusResponse]:
    order = await AdminService.mark_order_failed(order_id, current_admin, data.reason, _client_ip(request))
    return Response.ok(data=_order_status_response(order))


@router.post("/orders/{order_id}/file", response_model=Response[PaperOrderStatusResponse], summary="人工补发下载链接")
async def attach_order_file(
    order_id: int,
    data: AdminOrderManualFileRequest,
    request: Request,
    current_admin: User = Depends(get_current_admin_user),
) -> Response[PaperOrderStatusResponse]:
    order = await AdminService.attach_order_file(
        order_id,
        current_admin,
        data.download_url,
        data.file_key,
        data.reason,
        _client_ip(request),
    )
    return Response.ok(data=_order_status_response(order))


@router.get("/model-configs", response_model=Response[list[ModelConfigResponse]], summary="查询大模型配置")
async def list_model_configs(_: User = Depends(get_current_admin_user)) -> Response[list[ModelConfigResponse]]:
    return Response.ok(data=await AdminService.list_model_configs())


@router.post("/model-configs", response_model=Response[ModelConfigResponse], summary="创建大模型配置")
async def create_model_config(
    data: ModelConfigCreateRequest,
    request: Request,
    current_admin: User = Depends(get_current_admin_user),
) -> Response[ModelConfigResponse]:
    return Response.ok(data=await AdminService.create_model_config(data, current_admin, _client_ip(request)))


@router.patch("/model-configs/{config_id}", response_model=Response[ModelConfigResponse], summary="更新大模型配置")
async def update_model_config(
    config_id: int,
    data: ModelConfigUpdateRequest,
    request: Request,
    current_admin: User = Depends(get_current_admin_user),
) -> Response[ModelConfigResponse]:
    return Response.ok(data=await AdminService.update_model_config(config_id, data, current_admin, _client_ip(request)))


@router.delete("/model-configs/{config_id}", response_model=Response[None], summary="删除大模型配置")
async def delete_model_config(
    config_id: int,
    request: Request,
    current_admin: User = Depends(get_current_admin_user),
) -> Response[None]:
    await AdminService.delete_model_config(config_id, current_admin, _client_ip(request))
    return Response.ok()


@router.post("/model-configs/{config_id}/test", response_model=Response[dict[str, str]], summary="测试模型配置")
async def test_model_config(
    config_id: int,
    _: User = Depends(get_current_admin_user),
) -> Response[dict[str, str]]:
    configs = await AdminService.list_model_configs()
    config = next((item for item in configs if item.id == config_id), None)
    if config is None:
        return Response.error(code=404, message="模型配置不存在")
    status_text = "ok" if config.is_enabled and bool(config.masked_api_key) else "unconfigured"
    return Response.ok(data={"status": status_text, "message": "配置已保存，真实连通性将在模型调用时验证"})


@router.get("/model-call-logs", response_model=Response[PageResponse[dict]], summary="查询模型调用日志")
async def list_model_call_logs(
    page: int = 1,
    page_size: int = 10,
    _: User = Depends(get_current_admin_user),
) -> Response[PageResponse[dict]]:
    return Response.ok(data=await AdminService.list_model_call_logs(page, page_size))


@router.get("/audit-logs", response_model=Response[PageResponse[dict]], summary="查询审计日志")
async def list_audit_logs(
    page: int = 1,
    page_size: int = 10,
    _: User = Depends(get_current_admin_user),
) -> Response[PageResponse[dict]]:
    return Response.ok(data=await AdminService.list_audit_logs(page, page_size))
