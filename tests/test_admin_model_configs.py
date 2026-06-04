import pytest
from fastapi import HTTPException

from services.admin.model_configs import AdminModelConfigService


def test_model_config_rejects_deepseek_with_gemini_protocol() -> None:
    with pytest.raises(HTTPException) as exc_info:
        AdminModelConfigService._validate_model_protocol(
            provider="gemini-generate-content",
            model_name="deepseek-chat",
            api_base_url="https://api.deepseek.com",
        )

    assert exc_info.value.status_code == 400
    assert "OpenAI 兼容协议" in str(exc_info.value.detail)


def test_model_config_allows_deepseek_with_openai_compatible_protocol() -> None:
    AdminModelConfigService._validate_model_protocol(
        provider="openai-compatible",
        model_name="deepseek-chat",
        api_base_url="https://api.deepseek.com",
    )
