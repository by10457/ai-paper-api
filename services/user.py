"""
用户业务逻辑层

原则：
- Service 层只处理业务逻辑，不直接接触 HTTP Request/Response
- 数据库操作通过 ORM 模型完成
- 接口层（api/）只做参数校验和调用 service，不写业务逻辑
"""

import secrets

from core.config import settings
from core.logger import logger
from core.security import hash_password
from models.user import User
from schemas.user import UserCreate, UserUpdate


class UserService:
    @staticmethod
    async def get_by_username(username: str) -> User | None:
        return await User.filter(username=username).first()

    @staticmethod
    async def get_by_email(email: str) -> User | None:
        return await User.filter(email=email).first()

    @staticmethod
    async def create(data: UserCreate) -> User:
        user = await User.create(
            username=data.username,
            hashed_password=hash_password(data.password),
            avatar=data.avatar,
            nickname=data.nickname,
            email=data.email,
            points=settings.DEFAULT_USER_POINTS,
        )
        logger.info(f"新用户注册：{user.username} (id={user.id})")
        return user

    @staticmethod
    async def update(user: User, data: UserUpdate) -> User:
        update_data = data.model_dump(exclude_unset=True)
        if update_data:
            await user.update_from_dict(update_data).save()
        return user

    @staticmethod
    async def issue_api_token(user: User) -> str:
        if user.api_token:
            return user.api_token
        user.api_token = secrets.token_urlsafe(32)
        await user.save(update_fields=["api_token", "updated_at"])
        return user.api_token
