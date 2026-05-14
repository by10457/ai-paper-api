"""
用户业务逻辑层

原则：
- Service 层只处理业务逻辑，不直接接触 HTTP Request/Response
- 数据库操作通过 ORM 模型完成
- 接口层（api/）只做参数校验和调用 service，不写业务逻辑
"""

import secrets
from datetime import UTC, datetime
from decimal import Decimal

from core.config import settings
from core.logger import logger
from core.security import hash_password
from models.admin import RechargeOrder
from models.user import User
from schemas.common import PageResponse
from schemas.user import RechargeOrderCreateRequest, RechargeOrderResponse, UserCreate, UserUpdate

RECHARGE_STATUS_TEXT = {
    "pending": "待审核",
    "approved": "已入账",
    "rejected": "已驳回",
}


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
        user.api_token_created_at = datetime.now(UTC)
        user.api_token_call_count = 0
        await user.save(update_fields=["api_token", "api_token_created_at", "api_token_call_count", "updated_at"])
        return user.api_token

    @staticmethod
    async def reset_api_token(user: User) -> str:
        user.api_token = secrets.token_urlsafe(32)
        user.api_token_created_at = datetime.now(UTC)
        user.api_token_last_used_at = None
        user.api_token_call_count = 0
        await user.save(
            update_fields=[
                "api_token",
                "api_token_created_at",
                "api_token_last_used_at",
                "api_token_call_count",
                "updated_at",
            ]
        )
        return user.api_token

    @staticmethod
    async def create_recharge_order(user: User, data: RechargeOrderCreateRequest) -> RechargeOrderResponse:
        amount = (Decimal(data.points) / Decimal("10")).quantize(Decimal("0.01"))
        order = await RechargeOrder.create(
            user=user,
            order_sn=UserService._generate_recharge_sn(),
            points=data.points,
            amount=amount,
            pay_channel=data.pay_channel,
            remark=data.remark,
        )
        return UserService.recharge_order_response(order)

    @staticmethod
    async def list_recharge_orders(user: User, page: int, page_size: int) -> PageResponse[RechargeOrderResponse]:
        query = RechargeOrder.filter(user=user)
        total = await query.count()
        orders = await query.order_by("-id").offset((page - 1) * page_size).limit(page_size)
        return PageResponse(
            total=total,
            page=page,
            page_size=page_size,
            items=[UserService.recharge_order_response(item) for item in orders],
        )

    @staticmethod
    def recharge_order_response(order: RechargeOrder) -> RechargeOrderResponse:
        return RechargeOrderResponse(
            id=order.id,
            order_sn=order.order_sn,
            points=order.points,
            amount=float(order.amount),
            pay_channel=order.pay_channel,
            status=order.status,
            status_text=RECHARGE_STATUS_TEXT.get(order.status, order.status),
            remark=order.remark,
            admin_remark=order.admin_remark,
            created_at=order.created_at,
            reviewed_at=order.reviewed_at,
        )

    @staticmethod
    def _generate_recharge_sn() -> str:
        timestamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
        return f"RC{timestamp}{secrets.token_hex(4).upper()}"
