"""
认证与权限依赖

FastAPI 的依赖注入系统让你可以把「获取当前用户」
「验证权限」等逻辑抽成可复用的函数，在路由上直接声明使用。

使用方式：
    @router.get("/userInfo")
    async def get_user_info(current_user: User = Depends(get_current_user)):
        ...
"""

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError

from core.security import decode_access_token
from models.user import User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


async def get_current_user(token: str = Depends(oauth2_scheme)) -> User:
    """校验 JWT 并返回当前登录用户。"""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="无效的凭证",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = decode_access_token(token)
        subject = payload.get("sub")
        if not isinstance(subject, str):
            raise credentials_exception
        user_id = int(subject)
    except ValueError:
        raise credentials_exception from None
    except JWTError:
        raise credentials_exception from None

    user = await User.filter(id=user_id).first()
    if user is None:
        raise credentials_exception
    return user
