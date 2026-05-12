from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

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
    return user
