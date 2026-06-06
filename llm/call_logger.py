"""大模型调用日志写入服务。"""

from __future__ import annotations

import logging
from typing import Any

from models.admin import ModelCallLog
from services.thesis.generation.runtime_context import get_runtime_context

logger = logging.getLogger(__name__)


async def record_model_call(
    *,
    config_type: str,
    provider: str,
    model_name: str,
    status: str,
    call_type: str = "text",
    model_config_id: int | None = None,
    prompt_chars: int = 0,
    response_chars: int = 0,
    input_tokens: int = 0,
    output_tokens: int = 0,
    latency_ms: int = 0,
    error_message: str | None = None,
    metadata: dict[str, Any] | None = None,
    started_at: Any = None,
    completed_at: Any = None,
) -> None:
    """记录一次模型调用，日志失败时只降级为 debug。"""

    ctx = get_runtime_context()
    try:
        await ModelCallLog.create(
            user_id=ctx.user_id,
            order_id=ctx.order_id,
            generation_task_id=ctx.generation_task_id,
            model_config_id=model_config_id,
            config_type=config_type,
            call_type=call_type,
            task_id=ctx.task_id,
            stage=ctx.stage,
            provider=provider,
            model_name=model_name,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            prompt_chars=prompt_chars,
            response_chars=response_chars,
            latency_ms=latency_ms,
            status=status,
            error_message=error_message[:500] if error_message else None,
            metadata=metadata,
            started_at=started_at,
            completed_at=completed_at,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("写入大模型调用日志失败: {}", exc)


__all__ = ["record_model_call"]
