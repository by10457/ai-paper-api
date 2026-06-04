"""
用户业务逻辑层

原则：
- Service 层只处理业务逻辑，不直接接触 HTTP Request/Response
- 数据库操作通过 ORM 模型完成
- 接口层（api/）只做参数校验和调用 service，不写业务逻辑
"""

import secrets

from tortoise import timezone

from core.config import settings
from core.logger import logger
from core.security import hash_password
from models.user import User
from schemas.user import UserCreate, UserUpdate


class UserService:
    """用户侧账号和 API Token 业务。"""

    @staticmethod
    async def get_by_username(username: str) -> User | None:
        """根据用户名查询用户，不存在时返回 None。"""

        return await User.filter(username=username).first()

    @staticmethod
    async def get_by_email(email: str) -> User | None:
        """根据邮箱查询用户，不存在时返回 None。"""

        return await User.filter(email=email).first()

    @staticmethod
    async def create(data: UserCreate) -> User:
        """创建普通用户，并发放系统默认初始积分。"""

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
        """更新当前用户资料，只保存请求中显式传入的字段。"""

        update_data = data.model_dump(exclude_unset=True)
        if update_data:
            await user.update_from_dict(update_data).save()
        return user

    @staticmethod
    async def issue_api_token(user: User) -> str:
        """签发长期 API Token；已存在 token 时保持幂等并直接返回。"""

        if user.api_token:
            return user.api_token
        user.api_token = secrets.token_urlsafe(32)
        user.api_token_created_at = timezone.now()
        user.api_token_call_count = 0
        await user.save(update_fields=["api_token", "api_token_created_at", "api_token_call_count", "updated_at"])
        return user.api_token

    @staticmethod
    async def reset_api_token(user: User) -> str:
        """重置长期 API Token，并清空最近使用时间和调用次数。"""

        token = secrets.token_urlsafe(32)
        await user.update_from_dict(
            {
                "api_token": token,
                "api_token_created_at": timezone.now(),
                "api_token_last_used_at": None,
                "api_token_call_count": 0,
            }
        ).save(
            update_fields=[
                "api_token",
                "api_token_created_at",
                "api_token_last_used_at",
                "api_token_call_count",
                "updated_at",
            ]
        )
        return token
