from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from api.dependencies.api_token import get_api_token_user
from app import app
from services.thesis import order_workflow
from services.thesis.order_service import PaperOrderService


@pytest.fixture
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_paper_order_routes_are_registered() -> None:
    routes = {route.path for route in app.routes}
    assert "/api/v1/users/apiToken" in routes
    assert "/api/v1/users/points" in routes
    assert "/api/v1/thesis/price" in routes
    assert "/api/v1/thesis/outlines" in routes
    assert "/api/v1/thesis/orders" in routes
    assert "/api/v1/thesis/orders/pay" in routes
    assert "/api/v1/thesis/orders/status" in routes
    assert "/api/v1/thesis/orders/download-url" in routes


def test_paper_outline_record_success(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_current_user() -> SimpleNamespace:
        return SimpleNamespace(id=1, username="demo", points=300)

    async def fake_generate_outline(
        title: str,
        target_word_count: int,
        codetype: str,
        language: str,
        three_level: bool,
        aboutmsg: str,
    ) -> dict:
        assert target_word_count == 8000
        return {
            "outline": [{"chapter": "绪论", "sections": [{"name": "研究背景", "abstract": "背景"}]}],
            "abstract": f"{title}摘要",
            "keywords": "AI,论文",
        }

    async def fake_create_outline_record(user: SimpleNamespace, req: object, outline_data: dict) -> SimpleNamespace:
        assert user.username == "demo"
        assert outline_data["keywords"] == "AI,论文"
        return SimpleNamespace(id=123)

    app.dependency_overrides[get_api_token_user] = fake_current_user
    monkeypatch.setattr(order_workflow, "load_generate_outline", lambda: fake_generate_outline)
    monkeypatch.setattr(PaperOrderService, "create_outline_record", fake_create_outline_record)

    response = client.post(
        "/api/v1/thesis/outlines",
        headers={"Authorization": "Bearer test-token"},
        json={"title": "基于大模型的论文生成系统", "form_params": {"lengthnum": "8000"}},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["code"] == 200
    assert payload["data"]["record_id"] == 123
    assert payload["data"]["outline"][0]["chapter"] == "绪论"
