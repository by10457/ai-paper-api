"""开题报告、文献综述和任务书的独立订单与生成任务模型。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from tortoise import fields

from models.base import BaseModel

if TYPE_CHECKING:
    from models.user import User


class ThesisMaterialOrder(BaseModel):
    """论文材料订单，与论文正文订单隔离保存。"""

    user: fields.ForeignKeyRelation[User]
    user_id: int
    user = fields.ForeignKeyField("models.User", related_name="thesis_material_orders", description="用户")
    order_sn = fields.CharField(max_length=64, unique=True, description="论文材料订单号")
    document_type = fields.CharField(max_length=32, description="文档类型")
    idempotency_key = fields.CharField(max_length=128, null=True, description="请求幂等键")
    title = fields.CharField(max_length=200, description="文档标题")
    request_payload = fields.JSONField(description="生成请求快照")
    cost_points = fields.IntField(default=20, description="应扣积分")
    paid_points = fields.IntField(default=0, description="已扣积分")
    refunded_points = fields.IntField(default=0, description="已退积分")
    status = fields.CharField(max_length=32, default="paid", description="订单状态")
    task_id = fields.CharField(max_length=64, null=True, description="当前生成任务 ID")
    storage_provider = fields.CharField(max_length=32, null=True, description="主存储类型")
    file_key = fields.CharField(max_length=512, null=True, description="主存储文件 key")
    local_file_key = fields.CharField(max_length=512, null=True, description="本地兜底文件 key")
    download_url = fields.CharField(max_length=1024, null=True, description="下载链接")
    callback_url = fields.CharField(max_length=1024, null=True, description="生成完成回调地址")
    callback_secret = fields.CharField(max_length=255, null=True, description="生成完成回调密钥")
    last_error = fields.CharField(max_length=500, null=True, description="最近一次错误")
    paid_at = fields.DatetimeField(null=True, description="扣费时间")
    refunded_at = fields.DatetimeField(null=True, description="退积分时间")
    started_at = fields.DatetimeField(null=True, description="开始生成时间")
    completed_at = fields.DatetimeField(null=True, description="完成时间")
    retry_count = fields.IntField(default=0, description="自动重试次数")
    next_retry_at = fields.DatetimeField(null=True, description="下次自动重试时间")

    class Meta:
        # 数据库沿用既有 paper 前缀，代码领域名统一使用 thesis。
        table = "paper_material_orders"
        table_description = "论文材料订单"
        unique_together = (("user", "idempotency_key"),)
        indexes = (("user", "document_type", "created_at"), ("status", "next_retry_at"))


class ThesisMaterialGenerationTask(BaseModel):
    """论文材料生成任务，保存进度、结构化结果与文件信息。"""

    user: fields.ForeignKeyRelation[User]
    order: fields.ForeignKeyRelation[ThesisMaterialOrder]
    user_id: int
    order_id: int
    user = fields.ForeignKeyField(
        "models.User",
        related_name="thesis_material_generation_tasks",
        description="用户",
    )
    order = fields.ForeignKeyField(
        "models.ThesisMaterialOrder",
        related_name="generation_tasks",
        description="关联论文材料订单",
    )
    idempotency_key = fields.CharField(max_length=128, null=True, description="请求幂等键")
    task_id = fields.CharField(max_length=64, unique=True, description="生成任务 ID")
    document_type = fields.CharField(max_length=32, description="文档类型")
    title = fields.CharField(max_length=200, description="文档标题")
    status = fields.CharField(max_length=32, default="paid", description="任务状态")
    current_stage = fields.CharField(max_length=64, null=True, description="当前生成阶段")
    progress = fields.IntField(default=0, description="当前生成进度")
    process_events = fields.JSONField(null=True, description="生成过程事件")
    process_metadata = fields.JSONField(null=True, description="生成过程关键数据")
    result_data = fields.JSONField(null=True, description="结构化文档生成结果")
    storage_provider = fields.CharField(max_length=32, null=True, description="主存储类型")
    file_key = fields.CharField(max_length=512, null=True, description="主存储文件 key")
    local_file_key = fields.CharField(max_length=512, null=True, description="本地兜底文件 key")
    last_error = fields.CharField(max_length=500, null=True, description="最近一次错误")
    started_at = fields.DatetimeField(null=True, description="开始生成时间")
    completed_at = fields.DatetimeField(null=True, description="完成时间")
    retry_count = fields.IntField(default=0, description="自动重试次数")
    next_retry_at = fields.DatetimeField(null=True, description="下次自动重试时间")

    class Meta:
        # 数据库沿用既有 paper 前缀，代码领域名统一使用 thesis。
        table = "paper_material_generation_tasks"
        table_description = "论文材料生成任务"
        unique_together = (("user", "idempotency_key"),)
        indexes = (("status", "next_retry_at"), ("document_type", "status", "updated_at"))
