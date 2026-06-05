import asyncio

from core.config import get_settings
from services.thesis.content import reference_service_serpapi as reference_service


class _FakeResponse:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {"message": {"items": []}}


class _FakeClient:
    def __init__(self) -> None:
        self.params = None

    async def get(self, url: str, params: dict):
        self.params = params
        return _FakeResponse()


def test_crossref_uses_mailto_from_env(monkeypatch) -> None:
    monkeypatch.setenv("CROSSREF_MAILTO", "test@example.com")
    get_settings.cache_clear()
    client = _FakeClient()

    asyncio.run(reference_service._query_crossref_one(client, "A title"))

    assert client.params["mailto"] == "test@example.com"
    get_settings.cache_clear()


def test_crossref_uses_default_mailto(monkeypatch) -> None:
    monkeypatch.delenv("CROSSREF_MAILTO", raising=False)
    get_settings.cache_clear()
    client = _FakeClient()

    asyncio.run(reference_service._query_crossref_one(client, "A title"))

    assert client.params["mailto"] == "noreply@example.com"
    get_settings.cache_clear()
