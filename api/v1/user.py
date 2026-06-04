"""用户自助接口路由。"""

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
    UserCreate,
    UserPointsResponse,
    UserResponse,
    UserUpdate,
)
from services.admin import mask_secret
from services.user import UserService

router = APIRouter()


async def _ensure_username_available(username: str, *, exclude_user_id: int | None = None) -> None:
    """校验用户名未被其他用户占用。"""

    existing_user = await UserService.get_by_username(username)
    if existing_user is not None and existing_user.id != exclude_user_id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="用户名已存在")


async def _ensure_email_available(email: str, *, exclude_user_id: int | None = None) -> None:
    """校验邮箱未被其他用户占用。"""

    existing_user = await UserService.get_by_email(email)
    if existing_user is not None and existing_user.id != exclude_user_id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="邮箱已存在")


async def _authenticate_api_token_user(data: ApiTokenLogin) -> User:
    """校验账号密码并返回可签发长期调用 Token 的用户。"""

    user = await UserService.get_by_username(data.username)
    if user is None or not verify_password(data.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")
    if user.is_disabled:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="账号已禁用")
    return user


def _api_token_response(user: User, token: str) -> ApiTokenResponse:
    """组装长期调用 Token 响应，避免在多个接口重复字段映射。"""

    return ApiTokenResponse(
        token=token,
        username=user.username,
        points=user.points,
        masked_token=mask_secret(token),
        created_at=user.api_token_created_at,
        last_used_at=user.api_token_last_used_at,
        call_count=user.api_token_call_count,
    )


def _api_token_info_response(user: User) -> ApiTokenInfoResponse:
    """组装当前用户长期调用 Token 信息。"""

    return ApiTokenInfoResponse(
        has_token=bool(user.api_token),
        masked_token=mask_secret(user.api_token),
        created_at=user.api_token_created_at,
        last_used_at=user.api_token_last_used_at,
        call_count=user.api_token_call_count,
    )


@router.post("/register", response_model=Response[UserResponse], summary="注册用户")
async def register_user(data: UserCreate) -> Response[UserResponse]:
    """注册普通用户账号。"""

    await _ensure_username_available(data.username)
    await _ensure_email_available(str(data.email))
    user = await UserService.create(data)
    return Response.ok(data=UserResponse.model_validate(user))


@router.get("/userInfo", response_model=Response[UserResponse], summary="查询当前用户信息")
async def get_user_info(current_user: User = Depends(get_current_user)) -> Response[UserResponse]:
    """查询当前登录用户信息。"""

    return Response.ok(data=UserResponse.model_validate(current_user))


@router.post("/updateInfo", response_model=Response[UserResponse], summary="更新当前用户信息")
async def update_info(
    data: UserUpdate,
    current_user: User = Depends(get_current_user),
) -> Response[UserResponse]:
    """更新当前登录用户信息。"""

    if data.username is not None:
        await _ensure_username_available(data.username, exclude_user_id=current_user.id)
    if data.email is not None:
        await _ensure_email_available(str(data.email), exclude_user_id=current_user.id)

    user = await UserService.update(current_user, data)
    return Response.ok(data=UserResponse.model_validate(user))


@router.post("/apiToken", response_model=Response[ApiTokenResponse], summary="账号密码换取长期调用 Token")
async def issue_api_token(data: ApiTokenLogin) -> Response[ApiTokenResponse]:
    """使用账号密码签发长期调用 Token。"""

    user = await _authenticate_api_token_user(data)
    token = await UserService.issue_api_token(user)
    return Response.ok(data=_api_token_response(user, token))


@router.get("/points", response_model=Response[UserPointsResponse], summary="查询当前用户积分")
async def get_points(current_user: User = Depends(get_current_user)) -> Response[UserPointsResponse]:
    """查询当前用户积分余额及折算金额。"""

    return Response.ok(data=UserPointsResponse(points=current_user.points, amount=current_user.points / 10))


@router.get("/apiToken", response_model=Response[ApiTokenInfoResponse], summary="查询当前用户调用 Token 信息")
async def get_api_token_info(current_user: User = Depends(get_current_user)) -> Response[ApiTokenInfoResponse]:
    """查询当前用户长期调用 Token 的脱敏信息。"""

    return Response.ok(data=_api_token_info_response(current_user))


@router.post("/apiToken/reset", response_model=Response[ApiTokenResponse], summary="重置当前用户调用 Token")
async def reset_api_token(current_user: User = Depends(get_current_user)) -> Response[ApiTokenResponse]:
    """重置当前用户长期调用 Token。"""

    token = await UserService.reset_api_token(current_user)
    return Response.ok(data=_api_token_response(current_user, token))


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
    """分页查询当前用户积分流水。"""

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
