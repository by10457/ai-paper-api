from fastapi import APIRouter, Depends, HTTPException, status

from api.dependencies.auth import get_current_user
from core.security import verify_password
from models.admin import PointLedger
from models.user import User
from schemas.common import PageResponse, Response
from schemas.user import (
    ApiTokenInfoResponse,
    ApiTokenLogin,
    ApiTokenResponse,
    PointLedgerResponse,
    RechargeOrderCreateRequest,
    RechargeOrderResponse,
    UserCreate,
    UserPointsResponse,
    UserResponse,
    UserUpdate,
)
from services.admin import mask_secret
from services.user import UserService

router = APIRouter()


@router.post("/register", response_model=Response[UserResponse], summary="注册用户")
async def register_user(data: UserCreate) -> Response[UserResponse]:
    if await UserService.get_by_username(data.username):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="用户名已存在")
    if await UserService.get_by_email(str(data.email)):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="邮箱已存在")
    user = await UserService.create(data)
    return Response.ok(data=UserResponse.model_validate(user))


@router.get("/userInfo", response_model=Response[UserResponse], summary="查询当前用户信息")
async def get_user_info(current_user: User = Depends(get_current_user)) -> Response[UserResponse]:
    return Response.ok(data=UserResponse.model_validate(current_user))


@router.post("/updateInfo", response_model=Response[UserResponse], summary="更新当前用户信息")
async def update_info(
    data: UserUpdate,
    current_user: User = Depends(get_current_user),
) -> Response[UserResponse]:
    if data.username is not None:
        existing_username = await UserService.get_by_username(data.username)
        if existing_username is not None and existing_username.id != current_user.id:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="用户名已存在")

    if data.email is not None:
        existing_email = await UserService.get_by_email(str(data.email))
        if existing_email is not None and existing_email.id != current_user.id:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="邮箱已存在")

    user = await UserService.update(current_user, data)
    return Response.ok(data=UserResponse.model_validate(user))


@router.post("/apiToken", response_model=Response[ApiTokenResponse], summary="账号密码换取长期调用 Token")
async def issue_api_token(data: ApiTokenLogin) -> Response[ApiTokenResponse]:
    user = await UserService.get_by_username(data.username)
    if user is None or not verify_password(data.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")
    if user.is_disabled:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="账号已禁用")
    token = await UserService.issue_api_token(user)
    return Response.ok(
        data=ApiTokenResponse(
            token=token,
            username=user.username,
            points=user.points,
            masked_token=mask_secret(token),
            created_at=user.api_token_created_at,
            last_used_at=user.api_token_last_used_at,
            call_count=user.api_token_call_count,
        )
    )


@router.get("/points", response_model=Response[UserPointsResponse], summary="查询当前用户积分")
async def get_points(current_user: User = Depends(get_current_user)) -> Response[UserPointsResponse]:
    return Response.ok(data=UserPointsResponse(points=current_user.points, amount=current_user.points / 10))


@router.get("/apiToken", response_model=Response[ApiTokenInfoResponse], summary="查询当前用户调用 Token 信息")
async def get_api_token_info(current_user: User = Depends(get_current_user)) -> Response[ApiTokenInfoResponse]:
    return Response.ok(
        data=ApiTokenInfoResponse(
            has_token=bool(current_user.api_token),
            masked_token=mask_secret(current_user.api_token),
            created_at=current_user.api_token_created_at,
            last_used_at=current_user.api_token_last_used_at,
            call_count=current_user.api_token_call_count,
        )
    )


@router.post("/apiToken/reset", response_model=Response[ApiTokenResponse], summary="重置当前用户调用 Token")
async def reset_api_token(current_user: User = Depends(get_current_user)) -> Response[ApiTokenResponse]:
    token = await UserService.reset_api_token(current_user)
    return Response.ok(
        data=ApiTokenResponse(
            token=token,
            username=current_user.username,
            points=current_user.points,
            masked_token=mask_secret(token),
            created_at=current_user.api_token_created_at,
            last_used_at=current_user.api_token_last_used_at,
            call_count=current_user.api_token_call_count,
        )
    )


@router.get(
    "/points/ledger",
    response_model=Response[PageResponse[PointLedgerResponse]],
    summary="查询当前用户积分流水",
)
async def list_point_ledgers(
    page: int = 1,
    page_size: int = 10,
    current_user: User = Depends(get_current_user),
) -> Response[PageResponse[PointLedgerResponse]]:
    query = PointLedger.filter(user=current_user)
    total = await query.count()
    ledgers = await query.order_by("-id").offset((page - 1) * page_size).limit(page_size)
    return Response.ok(
        data=PageResponse(
            total=total,
            page=page,
            page_size=page_size,
            items=[PointLedgerResponse.model_validate(item) for item in ledgers],
        )
    )


@router.post(
    "/points/recharge",
    response_model=Response[RechargeOrderResponse],
    summary="创建积分充值申请",
)
async def create_recharge_order(
    data: RechargeOrderCreateRequest,
    current_user: User = Depends(get_current_user),
) -> Response[RechargeOrderResponse]:
    return Response.ok(data=await UserService.create_recharge_order(current_user, data))


@router.get(
    "/points/recharge",
    response_model=Response[PageResponse[RechargeOrderResponse]],
    summary="查询当前用户充值申请",
)
async def list_recharge_orders(
    page: int = 1,
    page_size: int = 10,
    current_user: User = Depends(get_current_user),
) -> Response[PageResponse[RechargeOrderResponse]]:
    return Response.ok(data=await UserService.list_recharge_orders(current_user, page, page_size))
