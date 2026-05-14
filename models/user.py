"""
用户模型示例
"""

from tortoise import fields

from models.base import BaseModel


class User(BaseModel):
    username = fields.CharField(max_length=64, unique=True, description="用户名")
    hashed_password = fields.CharField(max_length=256, description="哈希密码")
    avatar = fields.CharField(max_length=512, null=True, description="头像地址")
    nickname = fields.CharField(max_length=64, null=True, description="昵称")
    email = fields.CharField(max_length=128, unique=True, description="邮箱")
    points = fields.IntField(default=0, description="积分余额")
    api_token = fields.CharField(max_length=128, unique=True, null=True, description="长期调用 Token")
    api_token_created_at = fields.DatetimeField(null=True, description="调用 Token 创建时间")
    api_token_last_used_at = fields.DatetimeField(null=True, description="调用 Token 最近使用时间")
    api_token_call_count = fields.IntField(default=0, description="调用 Token 使用次数")
    role = fields.CharField(max_length=32, default="user", description="角色：user/admin")
    is_disabled = fields.BooleanField(default=False, description="是否禁用")
    last_login_at = fields.DatetimeField(null=True, description="最近登录时间")

    class Meta:
        table = "users"
        table_description = "用户表"

    def __str__(self) -> str:
        return f"User(id={self.id}, username={self.username})"
