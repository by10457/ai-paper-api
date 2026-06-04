"""认证接口路由。"""

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from tortoise import timezone

from core.security import create_access_token, verify_password
from models.user import User
from schemas.common import Response
from schemas.user import TokenResponse
from services.user import UserService

router = APIRouter()


async def _authenticate_user(username: str, password: str) -> User:
    """校验用户名密码并返回可登录用户。"""

    user = await UserService.get_by_username(username)
    if user is None or not verify_password(password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
        )
    if user.is_disabled:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="账号已禁用")
    return user


async def _record_login(user: User) -> None:
    """记录用户最近一次登录时间。"""

    user.last_login_at = timezone.now()
    await user.save(update_fields=["last_login_at", "updated_at"])


@router.post("/login", response_model=Response[TokenResponse], summary="登录获取 Token")
async def login(form_data: OAuth2PasswordRequestForm = Depends()) -> Response[TokenResponse]:
    """账号密码登录并签发后台访问 Token。"""

    user = await _authenticate_user(form_data.username, form_data.password)
    await _record_login(user)
    token = create_access_token(subject=user.id)
    return Response.ok(data=TokenResponse(access_token=token))
