from __future__ import annotations

from typing import TYPE_CHECKING

from tortoise import fields

from models.base import BaseModel

if TYPE_CHECKING:
    from models.user import User


class PaperOutlineRecord(BaseModel):
    user: fields.ForeignKeyRelation[User]
    user = fields.ForeignKeyField("models.User", related_name="paper_outlines", description="用户")
    title = fields.CharField(max_length=200, description="论文标题")
    request_payload = fields.JSONField(null=True, description="大纲请求快照")
    outline_data = fields.JSONField(description="大纲生成结果")

    class Meta:
        table = "paper_outline_records"
        table_description = "论文大纲记录"


class PaperOrder(BaseModel):
    user: fields.ForeignKeyRelation[User]
    outline_record: fields.ForeignKeyRelation[PaperOutlineRecord]
    user = fields.ForeignKeyField("models.User", related_name="paper_orders", description="用户")
    outline_record = fields.ForeignKeyField(
        "models.PaperOutlineRecord",
        related_name="paper_orders",
        description="大纲记录",
    )
    order_sn = fields.CharField(max_length=64, unique=True, description="论文订单号")
    title = fields.CharField(max_length=200, description="论文标题")
    outline_json = fields.JSONField(description="用户确认后的大纲")
    config_form = fields.JSONField(null=True, description="生成配置快照")
    template_id = fields.IntField(null=True, description="模板 ID")
    selftemp = fields.IntField(null=True, description="模板类型")
    service_ids = fields.JSONField(null=True, description="增值服务 ID")
    cost_points = fields.IntField(default=200, description="应扣积分")
    paid_points = fields.IntField(default=0, description="已扣积分")
    refunded_points = fields.IntField(default=0, description="已退积分")
    status = fields.CharField(max_length=32, default="created", description="订单状态")
    task_id = fields.CharField(max_length=64, null=True, description="生成任务 ID")
    file_key = fields.CharField(max_length=512, null=True, description="七牛文件 key")
    download_url = fields.CharField(max_length=1024, null=True, description="下载链接")
    last_error = fields.CharField(max_length=500, null=True, description="最近一次错误")
    paid_at = fields.DatetimeField(null=True, description="扣费时间")
    refunded_at = fields.DatetimeField(null=True, description="退积分时间")
    started_at = fields.DatetimeField(null=True, description="开始生成时间")
    completed_at = fields.DatetimeField(null=True, description="完成时间")

    class Meta:
        table = "paper_orders"
        table_description = "论文订单"
