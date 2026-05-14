from datetime import UTC, datetime

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from tortoise.expressions import F

from core.security import decode_access_token
from models.user import User

token_scheme = HTTPBearer(auto_error=False)


async def get_api_token_user(credentials: HTTPAuthorizationCredentials | None = Depends(token_scheme)) -> User:
    if credentials is None or credentials.scheme.lower() != "bearer" or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="缺少调用 Token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = await User.filter(api_token=credentials.credentials).first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的调用 Token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if user.is_disabled:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="账号已禁用")
    await User.filter(id=user.id).update(
        api_token_call_count=F("api_token_call_count") + 1,
        api_token_last_used_at=datetime.now(UTC),
    )
    await user.refresh_from_db()
    return user


async def get_api_token_or_jwt_user(credentials: HTTPAuthorizationCredentials | None = Depends(token_scheme)) -> User:
    """允许论文订单接口同时接受长期调用 Token 和后台登录 JWT。"""

    if credentials is None or credentials.scheme.lower() != "bearer" or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="缺少认证 Token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = await User.filter(api_token=credentials.credentials).first()
    if user is not None:
        if user.is_disabled:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="账号已禁用")
        await User.filter(id=user.id).update(
            api_token_call_count=F("api_token_call_count") + 1,
            api_token_last_used_at=datetime.now(UTC),
        )
        await user.refresh_from_db()
        return user

    try:
        payload = decode_access_token(credentials.credentials)
        subject = payload.get("sub")
        if not isinstance(subject, str):
            raise JWTError("invalid subject")
        user = await User.filter(id=int(subject)).first()
    except (JWTError, ValueError):
        user = None

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的认证 Token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if user.is_disabled:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="账号已禁用")
    return user
