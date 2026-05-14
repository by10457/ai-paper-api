from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, EmailStr, Field, field_validator

from schemas.thesis import PaperOrderStatusResponse
from schemas.user import MAX_BCRYPT_PASSWORD_BYTES, PointLedgerResponse, RechargeOrderResponse, UserResponse


class AdminOverviewResponse(BaseModel):
    today_user_count: int
    month_user_count: int
    total_user_count: int
    today_order_count: int
    month_order_count: int
    total_order_count: int
    today_spent_points: int
    month_spent_points: int
    total_spent_points: int
    generating_order_count: int
    failed_order_count: int
    completed_order_count: int
    model_call_count: int
    api_token_call_count: int
    health: dict[str, str]


class AdminUserCreateRequest(BaseModel):
    username: str = Field(..., min_length=2, max_length=64)
    password: str = Field(..., min_length=8, max_length=72)
    email: EmailStr
    nickname: str | None = Field(None, max_length=64)
    avatar: str | None = Field(None, max_length=512)
    initial_points: int = Field(default=0, ge=0)
    role: Literal["user", "admin"] = "user"

    @field_validator("password")
    @classmethod
    def validate_password_bytes(cls, value: str) -> str:
        if len(value.encode("utf-8")) > MAX_BCRYPT_PASSWORD_BYTES:
            raise ValueError("密码 UTF-8 编码后不能超过 72 字节")
        return value


class AdminUserUpdateRequest(BaseModel):
    nickname: str | None = Field(None, max_length=64)
    avatar: str | None = Field(None, max_length=512)
    email: EmailStr | None = None
    role: Literal["user", "admin"] | None = None
    is_disabled: bool | None = None


class AdminResetPasswordRequest(BaseModel):
    password: str = Field(..., min_length=8, max_length=72)

    @field_validator("password")
    @classmethod
    def validate_password_bytes(cls, value: str) -> str:
        if len(value.encode("utf-8")) > MAX_BCRYPT_PASSWORD_BYTES:
            raise ValueError("密码 UTF-8 编码后不能超过 72 字节")
        return value


class AdminPointAdjustRequest(BaseModel):
    delta: int = Field(..., description="正数充值，负数扣减")
    reason: str = Field(..., min_length=1, max_length=255)


class AdminRechargeReviewRequest(BaseModel):
    status: Literal["approved", "rejected"]
    admin_remark: str = Field(..., min_length=1, max_length=500)


class AdminRechargeOrderResponse(RechargeOrderResponse):
    user_id: int
    username: str
    reviewer_id: int | None = None


class AdminUserDetailResponse(BaseModel):
    user: UserResponse
    point_ledgers: list[PointLedgerResponse]
    order_count: int
    api_token: dict[str, Any]


class AdminOrderListItem(BaseModel):
    id: int
    order_sn: str
    user_id: int
    username: str
    title: str
    status: str
    cost_points: int
    paid_points: int
    refunded_points: int
    task_id: str | None
    file_key: str | None
    download_url: str | None
    last_error: str | None
    created_at: datetime
    paid_at: datetime | None
    completed_at: datetime | None


class AdminOrderDetailResponse(BaseModel):
    order: AdminOrderListItem
    config_form: dict[str, Any] | None
    outline_json: list[dict[str, Any]]
    request_payload: dict[str, Any] | None
    point_ledgers: list[PointLedgerResponse]


class AdminOrderManualFileRequest(BaseModel):
    download_url: str = Field(..., min_length=1, max_length=1024)
    file_key: str | None = Field(None, max_length=512)
    reason: str = Field(..., min_length=1, max_length=255)


class AdminOrderFailRequest(BaseModel):
    reason: str = Field(..., min_length=1, max_length=500)


class ModelConfigCreateRequest(BaseModel):
    config_type: Literal["outline", "fulltext", "figure", "default"]
    provider: str = Field(..., min_length=1, max_length=64)
    model_name: str = Field(..., min_length=1, max_length=128)
    api_base_url: str = Field(..., min_length=1, max_length=255)
    api_key: str = Field(..., min_length=1, max_length=1024)
    temperature: float = Field(default=0.7, ge=0, le=2)
    max_tokens: int = Field(default=4096, ge=1)
    timeout_seconds: int = Field(default=120, ge=1)
    is_enabled: bool = True
    is_default: bool = False
    remark: str | None = Field(None, max_length=255)


class ModelConfigUpdateRequest(BaseModel):
    config_type: Literal["outline", "fulltext", "figure", "default"] | None = None
    provider: str | None = Field(None, min_length=1, max_length=64)
    model_name: str | None = Field(None, min_length=1, max_length=128)
    api_base_url: str | None = Field(None, min_length=1, max_length=255)
    api_key: str | None = Field(None, min_length=1, max_length=1024)
    temperature: float | None = Field(None, ge=0, le=2)
    max_tokens: int | None = Field(None, ge=1)
    timeout_seconds: int | None = Field(None, ge=1)
    is_enabled: bool | None = None
    is_default: bool | None = None
    remark: str | None = Field(None, max_length=255)


class ModelConfigResponse(BaseModel):
    id: int
    config_type: str
    provider: str
    model_name: str
    api_base_url: str
    masked_api_key: str
    temperature: float
    max_tokens: int
    timeout_seconds: int
    is_enabled: bool
    is_default: bool
    remark: str | None
    created_at: datetime
    updated_at: datetime


class ModelCallLogResponse(BaseModel):
    id: int
    user_id: int | None
    order_id: int | None
    model_config_id: int | None
    config_type: str
    provider: str
    model_name: str
    input_tokens: int
    output_tokens: int
    latency_ms: int
    status: str
    error_message: str | None
    created_at: datetime


class AuditLogResponse(BaseModel):
    id: int
    operator_id: int | None
    action: str
    target_type: str
    target_id: str | None
    summary: str
    ip_address: str | None
    created_at: datetime


class AdminOrderActionResponse(PaperOrderStatusResponse):
    pass
