from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm

from core.security import create_access_token, verify_password
from schemas.common import Response
from schemas.user import TokenResponse
from services.user import UserService

router = APIRouter()


@router.post("/login", response_model=Response[TokenResponse], summary="登录获取 Token")
async def login(form_data: OAuth2PasswordRequestForm = Depends()) -> Response[TokenResponse]:
    user = await UserService.get_by_username(form_data.username)
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
        )
    if user.is_disabled:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="账号已禁用")

    user.last_login_at = datetime.now(UTC)
    await user.save(update_fields=["last_login_at", "updated_at"])
    token = create_access_token(subject=user.id)
    return Response.ok(data=TokenResponse(access_token=token))
