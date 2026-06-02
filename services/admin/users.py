"""管理端用户服务。"""

from fastapi import HTTPException, status
from tortoise.expressions import F, Q

from core.security import hash_password
from models.admin import PointLedger
from models.paper import PaperOrder
from models.user import User
from schemas.admin import (
    AdminPointAdjustRequest,
    AdminResetPasswordRequest,
    AdminUserCreateRequest,
    AdminUserDetailResponse,
    AdminUserUpdateRequest,
)
from schemas.common import PageResponse
from schemas.user import PointLedgerResponse, UserResponse
from services.admin.audit import write_audit_log
from services.admin.helpers import get_user_or_404
from services.admin.utils import mask_secret


class AdminUserService:
    """处理后台用户查询、创建、资料更新、密码重置和积分调整。"""

    @staticmethod
    async def list_users(page: int, page_size: int, keyword: str | None = None) -> PageResponse[UserResponse]:
        """分页查询用户，关键字会匹配用户名、邮箱和昵称。"""

        query = User.all()
        if keyword:
            query = query.filter(
                Q(username__icontains=keyword) | Q(email__icontains=keyword) | Q(nickname__icontains=keyword)
            )
        total = await query.count()
        users = await query.order_by("-id").offset((page - 1) * page_size).limit(page_size)
        return PageResponse(
            total=total,
            page=page,
            page_size=page_size,
            items=[UserResponse.model_validate(item) for item in users],
        )

    @staticmethod
    async def create_user(data: AdminUserCreateRequest, operator: User, ip_address: str | None = None) -> UserResponse:
        """由管理员创建用户；初始积分大于 0 时同步写入积分流水。"""

        if await User.filter(username=data.username).exists():
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="用户名已存在")
        if await User.filter(email=str(data.email)).exists():
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="邮箱已存在")
        user = await User.create(
            username=data.username,
            hashed_password=hash_password(data.password),
            email=str(data.email),
            nickname=data.nickname,
            avatar=data.avatar,
            points=data.initial_points,
            role=data.role,
        )
        if data.initial_points:
            await PointLedger.create(
                user=user,
                operator=operator,
                change_type="admin_grant",
                delta=data.initial_points,
                balance_after=user.points,
                reason="管理员创建账号初始积分",
            )
        await write_audit_log(
            operator=operator,
            action="create_user",
            target_type="user",
            target_id=user.id,
            summary=f"创建用户 {user.username}",
            after={"username": user.username, "role": user.role, "points": user.points},
            ip_address=ip_address,
        )
        return UserResponse.model_validate(user)

    @staticmethod
    async def get_user_detail(user_id: int) -> AdminUserDetailResponse:
        """查询用户详情，附带最近积分流水和 API Token 摘要。"""

        user = await get_user_or_404(user_id)
        ledgers = await PointLedger.filter(user=user).order_by("-id").limit(20)
        return AdminUserDetailResponse(
            user=UserResponse.model_validate(user),
            point_ledgers=[PointLedgerResponse.model_validate(item) for item in ledgers],
            order_count=await PaperOrder.filter(user=user).count(),
            api_token={
                "has_token": bool(user.api_token),
                "masked_token": mask_secret(user.api_token),
                "created_at": user.api_token_created_at,
                "last_used_at": user.api_token_last_used_at,
                "call_count": user.api_token_call_count,
            },
        )

    @staticmethod
    async def update_user(
        user_id: int,
        data: AdminUserUpdateRequest,
        operator: User,
        ip_address: str | None = None,
    ) -> UserResponse:
        """更新用户资料、角色或禁用状态，并记录变更快照。"""

        user = await get_user_or_404(user_id)
        before = {
            "email": user.email,
            "nickname": user.nickname,
            "role": user.role,
            "is_disabled": user.is_disabled,
        }
        update_data = data.model_dump(exclude_unset=True)
        if "email" in update_data and update_data["email"] is not None:
            # 邮箱唯一性需要排除当前用户，避免用户保存原邮箱时被误判冲突。
            exists = await User.filter(email=str(update_data["email"])).exclude(id=user.id).exists()
            if exists:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="邮箱已存在")
            update_data["email"] = str(update_data["email"])
        if update_data:
            await user.update_from_dict(update_data).save()
        await write_audit_log(
            operator=operator,
            action="update_user",
            target_type="user",
            target_id=user.id,
            summary=f"更新用户 {user.username}",
            before=before,
            after=update_data,
            ip_address=ip_address,
        )
        return UserResponse.model_validate(user)

    @staticmethod
    async def reset_password(
        user_id: int,
        data: AdminResetPasswordRequest,
        operator: User,
        ip_address: str | None = None,
    ) -> None:
        """管理员重置用户密码。"""

        user = await get_user_or_404(user_id)
        user.hashed_password = hash_password(data.password)
        await user.save(update_fields=["hashed_password", "updated_at"])
        await write_audit_log(
            operator=operator,
            action="reset_password",
            target_type="user",
            target_id=user.id,
            summary=f"重置用户 {user.username} 密码",
            ip_address=ip_address,
        )

    @staticmethod
    async def adjust_points(
        user_id: int,
        data: AdminPointAdjustRequest,
        operator: User,
        ip_address: str | None = None,
    ) -> PointLedgerResponse:
        """管理员调整用户积分，禁止产生负余额。"""

        user = await get_user_or_404(user_id)
        if data.delta == 0:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="积分变更不能为 0")
        if data.delta < 0 and user.points + data.delta < 0:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="扣减后积分不能为负数")
        # 使用数据库表达式更新积分，避免并发调整时覆盖其他已提交的积分变化。
        await User.filter(id=user.id).update(points=F("points") + data.delta)
        await user.refresh_from_db()
        ledger = await PointLedger.create(
            user=user,
            operator=operator,
            change_type="admin_adjust",
            delta=data.delta,
            balance_after=user.points,
            reason=data.reason,
        )
        await write_audit_log(
            operator=operator,
            action="adjust_points",
            target_type="user",
            target_id=user.id,
            summary=f"调整用户 {user.username} 积分 {data.delta}",
            before={"points": user.points - data.delta},
            after={"points": user.points, "reason": data.reason},
            ip_address=ip_address,
        )
        return PointLedgerResponse.model_validate(ledger)
