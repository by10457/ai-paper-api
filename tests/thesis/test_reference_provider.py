import asyncio

from core.config import get_settings
from services.thesis.content import reference_service


def test_reference_provider_defaults_to_wfapi(monkeypatch) -> None:
    async def fake_wfapi_generate_references(*args, **kwargs) -> str:
        return "[1]中文文献."

    async def fake_serpapi_generate_references(*args, **kwargs) -> str:
        raise AssertionError("默认模式不应调用 SerpAPI")

    monkeypatch.delenv("REFERENCE_PROVIDER_MODE", raising=False)
    monkeypatch.setattr(reference_service.reference_service_wfapi, "generate_references", fake_wfapi_generate_references)
    monkeypatch.setattr(reference_service.reference_service_serpapi, "generate_references", fake_serpapi_generate_references)
    get_settings.cache_clear()

    references = asyncio.run(reference_service.generate_references("题目", "大纲", wxnum=5))

    assert references == "[1]中文文献."
    get_settings.cache_clear()


def test_reference_provider_mixed_renumbers_lines(monkeypatch) -> None:
    async def fake_wfapi_generate_references(*args, **kwargs) -> str:
        return "[1]中文文献一.\n[2]中文文献二."

    async def fake_serpapi_generate_references(*args, **kwargs) -> str:
        assert kwargs["include_chinese"] is False
        return "[1]English reference."

    monkeypatch.setenv("REFERENCE_PROVIDER_MODE", "mixed")
    monkeypatch.setattr(reference_service.reference_service_wfapi, "generate_references", fake_wfapi_generate_references)
    monkeypatch.setattr(reference_service.reference_service_serpapi, "generate_references", fake_serpapi_generate_references)
    get_settings.cache_clear()

    references = asyncio.run(reference_service.generate_references("题目", "大纲", wxnum=3))

    assert references == "[1]中文文献一.\n[2]中文文献二.\n[3]English reference."
    get_settings.cache_clear()
