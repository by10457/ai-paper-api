from typing import Any

import httpx
import pytest
from langchain_core.messages import HumanMessage, SystemMessage

from llm.client import GeminiGenerateContentChatModel, LLMProviderConfigError, LLMProviderQuotaError


@pytest.mark.asyncio
async def test_gemini_generate_content_model_uses_async_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_payload: dict[str, Any] = {}

    async def fake_request(
        self: GeminiGenerateContentChatModel,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        del self
        captured_payload.update(payload)
        return {"candidates": [{"content": {"parts": [{"text": "异步响应"}]}}]}

    monkeypatch.setattr(GeminiGenerateContentChatModel, "_arequest_generate_content", fake_request)

    model = GeminiGenerateContentChatModel(
        model_name="gemini-test",
        api_key="test-key",
        base_url="https://generativelanguage.googleapis.com",
        temperature=0.2,
        max_tokens=128,
    )
    result = await model._agenerate(
        [
            SystemMessage(content="你是论文助手"),
            HumanMessage(content="生成摘要"),
        ],
        stop=["END"],
    )

    assert result.generations[0].message.content == "异步响应"
    assert captured_payload["systemInstruction"]["parts"][0]["text"] == "你是论文助手"
    assert captured_payload["contents"] == [{"role": "user", "parts": [{"text": "生成摘要"}]}]
    assert captured_payload["generationConfig"] == {
        "temperature": 0.2,
        "maxOutputTokens": 128,
        "stopSequences": ["END"],
    }


def test_gemini_generate_content_quota_error_is_sanitized() -> None:
    model = GeminiGenerateContentChatModel(
        model_name="gemini-test",
        api_key="test-key",
        base_url="https://cdn.12ai.org",
    )
    response = httpx.Response(
        status_code=403,
        json={
            "error": {
                "message": "用户额度不足, 剩余额度: ¥-0.499362",
                "code": "insufficient_user_quota",
            }
        },
    )

    with pytest.raises(LLMProviderQuotaError, match="模型供应商账号额度不足"):
        model._raise_http_error(response)


def test_gemini_generate_content_auth_error_is_sanitized() -> None:
    model = GeminiGenerateContentChatModel(
        model_name="deepseek-chat",
        api_key="test-key",
        base_url="https://api.deepseek.com",
    )
    response = httpx.Response(status_code=401, text="Authentication Fails (governor)")

    with pytest.raises(LLMProviderConfigError, match="模型供应商认证失败"):
        model._raise_http_error(response)
