"""
Tortoise-ORM 模型基类

所有业务模型继承 BaseModel，自动获得：
- id        : 自增主键
- created_at: 创建时间（自动填充）
- updated_at: 更新时间（自动更新）
"""

from tortoise import fields
from tortoise.models import Model


class BaseModel(Model):
    id = fields.IntField(pk=True)
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        abstract = True
