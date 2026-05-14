from __future__ import annotations

from typing import TYPE_CHECKING

from tortoise import fields

from models.base import BaseModel

if TYPE_CHECKING:
    from models.paper import PaperOrder
    from models.user import User


class PointLedger(BaseModel):
    """积分流水，记录所有积分增减。"""

    user: fields.ForeignKeyRelation[User]
    operator: fields.ForeignKeyNullableRelation[User]
    order: fields.ForeignKeyNullableRelation[PaperOrder]
    user = fields.ForeignKeyField("models.User", related_name="point_ledgers", description="积分所属用户")
    operator = fields.ForeignKeyField(
        "models.User",
        related_name="operated_point_ledgers",
        null=True,
        description="操作人，系统动作可为空",
    )
    order = fields.ForeignKeyField("models.PaperOrder", related_name="point_ledgers", null=True, description="关联订单")
    change_type = fields.CharField(max_length=32, description="流水类型")
    delta = fields.IntField(description="积分变化，正数增加，负数扣减")
    balance_after = fields.IntField(description="变更后余额")
    reason = fields.CharField(max_length=255, description="变更原因")
    metadata = fields.JSONField(null=True, description="扩展信息")

    class Meta:
        table = "point_ledgers"
        table_description = "积分流水"


class RechargeOrder(BaseModel):
    """用户积分充值申请。"""

    user: fields.ForeignKeyRelation[User]
    reviewer: fields.ForeignKeyNullableRelation[User]
    user = fields.ForeignKeyField("models.User", related_name="recharge_orders", description="申请用户")
    reviewer = fields.ForeignKeyField(
        "models.User",
        related_name="reviewed_recharge_orders",
        null=True,
        description="审核管理员",
    )
    order_sn = fields.CharField(max_length=64, unique=True, description="充值申请单号")
    points = fields.IntField(description="申请充值积分")
    amount = fields.DecimalField(max_digits=10, decimal_places=2, description="折算金额")
    pay_channel = fields.CharField(max_length=32, default="manual", description="支付/沟通渠道")
    status = fields.CharField(max_length=32, default="pending", description="pending/approved/rejected")
    remark = fields.CharField(max_length=500, null=True, description="用户备注")
    admin_remark = fields.CharField(max_length=500, null=True, description="管理员备注")
    reviewed_at = fields.DatetimeField(null=True, description="审核时间")

    class Meta:
        table = "recharge_orders"
        table_description = "用户积分充值申请"


class ModelConfig(BaseModel):
    """大模型配置。"""

    config_type = fields.CharField(max_length=32, description="用途：outline/fulltext/figure/default")
    provider = fields.CharField(max_length=64, description="模型供应商")
    model_name = fields.CharField(max_length=128, description="模型名称")
    api_base_url = fields.CharField(max_length=255, description="API Base URL")
    api_key = fields.CharField(max_length=1024, description="API Key")
    temperature = fields.FloatField(default=0.7, description="温度")
    max_tokens = fields.IntField(default=4096, description="最大 token")
    timeout_seconds = fields.IntField(default=120, description="超时时间")
    is_enabled = fields.BooleanField(default=True, description="是否启用")
    is_default = fields.BooleanField(default=False, description="是否默认")
    remark = fields.CharField(max_length=255, null=True, description="备注")

    class Meta:
        table = "model_configs"
        table_description = "大模型配置"


class ModelCallLog(BaseModel):
    """大模型调用日志。"""

    user: fields.ForeignKeyNullableRelation[User]
    order: fields.ForeignKeyNullableRelation[PaperOrder]
    model_config: fields.ForeignKeyNullableRelation[ModelConfig]
    user = fields.ForeignKeyField("models.User", related_name="model_call_logs", null=True, description="用户")
    order = fields.ForeignKeyField("models.PaperOrder", related_name="model_call_logs", null=True, description="订单")
    model_config = fields.ForeignKeyField(
        "models.ModelConfig",
        related_name="call_logs",
        null=True,
        description="模型配置",
    )
    config_type = fields.CharField(max_length=32, description="调用用途")
    provider = fields.CharField(max_length=64, description="模型供应商")
    model_name = fields.CharField(max_length=128, description="模型名称")
    input_tokens = fields.IntField(default=0, description="输入 token")
    output_tokens = fields.IntField(default=0, description="输出 token")
    latency_ms = fields.IntField(default=0, description="耗时毫秒")
    status = fields.CharField(max_length=32, description="调用状态")
    error_message = fields.CharField(max_length=500, null=True, description="错误信息")

    class Meta:
        table = "model_call_logs"
        table_description = "大模型调用日志"


class SystemConfig(BaseModel):
    """系统配置键值。"""

    key = fields.CharField(max_length=128, unique=True, description="配置键")
    value = fields.TextField(description="配置值")
    description = fields.CharField(max_length=255, null=True, description="说明")

    class Meta:
        table = "system_configs"
        table_description = "系统配置"


class AuditLog(BaseModel):
    """管理员关键操作审计日志。"""

    operator: fields.ForeignKeyNullableRelation[User]
    operator = fields.ForeignKeyField("models.User", related_name="audit_logs", null=True, description="操作人")
    action = fields.CharField(max_length=64, description="操作类型")
    target_type = fields.CharField(max_length=64, description="目标类型")
    target_id = fields.CharField(max_length=64, null=True, description="目标 ID")
    summary = fields.CharField(max_length=500, description="操作摘要")
    before = fields.JSONField(null=True, description="变更前")
    after = fields.JSONField(null=True, description="变更后")
    ip_address = fields.CharField(max_length=64, null=True, description="IP")

    class Meta:
        table = "audit_logs"
        table_description = "审计日志"
