"""管理端大模型配置服务。"""

from __future__ import annotations

from typing import Any

from models.admin import ModelConfig
from models.user import User
from schemas.admin import ModelConfigCreateRequest, ModelConfigResponse, ModelConfigUpdateRequest
from services.admin.audit import write_audit_log
from services.admin.helpers import get_model_config_or_404
from services.admin.utils import mask_secret


class AdminModelConfigService:
    """维护不同用途的大模型供应商、模型名和密钥配置。"""

    @staticmethod
    async def list_model_configs() -> list[ModelConfigResponse]:
        """按用途和默认状态列出模型配置。"""

        configs = await ModelConfig.all().order_by("config_type", "-is_default", "-id")
        return [AdminModelConfigService._model_config_response(item) for item in configs]

    @staticmethod
    async def create_model_config(
        data: ModelConfigCreateRequest,
        operator: User,
        ip_address: str | None = None,
    ) -> ModelConfigResponse:
        """创建模型配置；新配置设为默认时会取消同用途旧默认配置。"""

        if data.is_default:
            # 同一 config_type 只允许存在一个默认配置，避免调用侧选择模型时产生歧义。
            await ModelConfig.filter(config_type=data.config_type).update(is_default=False)
        config = await ModelConfig.create(**data.model_dump())
        await write_audit_log(
            operator=operator,
            action="create_model_config",
            target_type="model_config",
            target_id=config.id,
            summary=f"创建模型配置 {config.config_type}/{config.model_name}",
            after={"config_type": config.config_type, "provider": config.provider, "model_name": config.model_name},
            ip_address=ip_address,
        )
        return AdminModelConfigService._model_config_response(config)

    @staticmethod
    async def update_model_config(
        config_id: int,
        data: ModelConfigUpdateRequest,
        operator: User,
        ip_address: str | None = None,
    ) -> ModelConfigResponse:
        """更新模型配置，并记录变更前后的可审计快照。"""

        config = await get_model_config_or_404(config_id)
        before = AdminModelConfigService._model_config_snapshot(config)
        update_data = data.model_dump(exclude_unset=True)
        next_type = str(update_data.get("config_type") or config.config_type)
        if update_data.get("is_default"):
            # 允许修改用途时同时设置默认，因此按更新后的 config_type 清理旧默认项。
            await ModelConfig.filter(config_type=next_type).exclude(id=config.id).update(is_default=False)
        if update_data:
            await config.update_from_dict(update_data).save()
        await write_audit_log(
            operator=operator,
            action="update_model_config",
            target_type="model_config",
            target_id=config.id,
            summary=f"更新模型配置 {config.config_type}/{config.model_name}",
            before=before,
            after=AdminModelConfigService._model_config_snapshot(config),
            ip_address=ip_address,
        )
        return AdminModelConfigService._model_config_response(config)

    @staticmethod
    async def delete_model_config(config_id: int, operator: User, ip_address: str | None = None) -> None:
        """删除模型配置，并在审计日志中保留脱敏后的配置快照。"""

        config = await get_model_config_or_404(config_id)
        before = AdminModelConfigService._model_config_snapshot(config)
        await config.delete()
        await write_audit_log(
            operator=operator,
            action="delete_model_config",
            target_type="model_config",
            target_id=config_id,
            summary=f"删除模型配置 {before['config_type']}/{before['model_name']}",
            before=before,
            ip_address=ip_address,
        )

    @staticmethod
    def _model_config_response(config: ModelConfig) -> ModelConfigResponse:
        """转换为管理端响应结构，避免泄露完整 API Key。"""

        return ModelConfigResponse(
            id=config.id,
            config_type=config.config_type,
            provider=config.provider,
            model_name=config.model_name,
            api_base_url=config.api_base_url,
            masked_api_key=mask_secret(config.api_key),
            is_enabled=config.is_enabled,
            is_default=config.is_default,
            remark=config.remark,
            created_at=config.created_at,
            updated_at=config.updated_at,
        )

    @staticmethod
    def _model_config_snapshot(config: ModelConfig) -> dict[str, Any]:
        """生成审计日志使用的配置快照，敏感字段只保留脱敏值。"""

        return {
            "config_type": config.config_type,
            "provider": config.provider,
            "model_name": config.model_name,
            "api_base_url": config.api_base_url,
            "masked_api_key": mask_secret(config.api_key),
            "is_enabled": config.is_enabled,
            "is_default": config.is_default,
            "remark": config.remark,
        }
