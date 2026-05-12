from fastapi import APIRouter, Depends, HTTPException, status

from api.dependencies.auth import get_current_user
from core.security import verify_password
from models.user import User
from schemas.common import Response
from schemas.user import ApiTokenLogin, ApiTokenResponse, UserCreate, UserPointsResponse, UserResponse, UserUpdate
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
    token = await UserService.issue_api_token(user)
    return Response.ok(data=ApiTokenResponse(token=token, username=user.username, points=user.points))


@router.get("/points", response_model=Response[UserPointsResponse], summary="查询当前用户积分")
async def get_points(current_user: User = Depends(get_current_user)) -> Response[UserPointsResponse]:
    return Response.ok(data=UserPointsResponse(points=current_user.points, amount=current_user.points / 10))
