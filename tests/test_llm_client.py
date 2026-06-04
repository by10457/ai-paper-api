from typing import Any

import pytest
from langchain_core.messages import HumanMessage, SystemMessage

from llm.client import GeminiGenerateContentChatModel


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
