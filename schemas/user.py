"""
用户相关的 Pydantic Schema

命名约定：
- XxxCreate   : 创建请求体（POST）
- XxxUpdate   : 更新请求体，字段通常 Optional
- XxxResponse : 响应体（对外暴露，不含敏感字段）
- XxxInDB     : 数据库完整字段（含 hashed_password 等，内部用）
"""

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator

MAX_BCRYPT_PASSWORD_BYTES = 72


class UserCreate(BaseModel):
    username: str = Field(..., min_length=2, max_length=64, description="用户名")
    password: str = Field(..., min_length=8, max_length=72, description="明文密码（服务端哈希存储）")
    avatar: str | None = Field(None, max_length=512, description="头像地址")
    nickname: str | None = Field(None, max_length=64, description="昵称")
    email: EmailStr = Field(..., description="邮箱")

    @field_validator("password")
    @classmethod
    def validate_password_bytes(cls, value: str) -> str:
        if len(value.encode("utf-8")) > MAX_BCRYPT_PASSWORD_BYTES:
            raise ValueError("密码 UTF-8 编码后不能超过 72 字节")
        return value


class UserUpdate(BaseModel):
    username: str | None = Field(None, min_length=2, max_length=64)
    avatar: str | None = Field(None, max_length=512)
    nickname: str | None = Field(None, max_length=64)
    email: EmailStr | None = None


class UserResponse(BaseModel):
    id: int
    username: str
    avatar: str | None
    nickname: str | None
    email: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}  # 支持从 ORM 对象直接转换


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
