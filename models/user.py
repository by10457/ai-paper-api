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

    class Meta:
        table = "users"
        table_description = "用户表"

    def __str__(self) -> str:
        return f"User(id={self.id}, username={self.username})"
