import asyncio
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from api.dependencies.api_token import get_api_token_or_jwt_user
from app import app
from services.thesis.business import order_workflow
from services.thesis.business.order_service import PaperOrderService
from services.thesis.storage.qiniu_uploader import build_qiniu_private_download_url


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

    app.dependency_overrides[get_api_token_or_jwt_user] = fake_current_user
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


def test_paper_order_create_passes_idempotency_key(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    captured_keys: list[str | None] = []

    async def fake_current_user() -> SimpleNamespace:
        return SimpleNamespace(id=1, username="demo", points=300)

    async def fake_create_order(
        user: SimpleNamespace,
        req: object,
        idempotency_key: str | None = None,
    ) -> SimpleNamespace:
        del req
        assert user.username == "demo"
        captured_keys.append(idempotency_key)
        return SimpleNamespace(order_sn="AP001", cost_points=200)

    app.dependency_overrides[get_api_token_or_jwt_user] = fake_current_user
    monkeypatch.setattr(PaperOrderService, "create_order", fake_create_order)

    response = client.post(
        "/api/v1/thesis/orders",
        headers={"Authorization": "Bearer test-token", "Idempotency-Key": "wxy-paper-order-1"},
        json={
            "record_id": 1,
            "outline": [
                {
                    "chapter": "绪论",
                    "sections": [
                        {"name": "研究背景", "abstract": "背景"},
                    ],
                }
            ],
        },
    )

    assert response.status_code == 200
    assert response.json()["data"]["order_sn"] == "AP001"
    assert captured_keys == ["wxy-paper-order-1"]


def test_qiniu_private_download_url_uses_configured_domain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "services.thesis.storage.qiniu_uploader.get_settings",
        lambda: SimpleNamespace(
            qiniu_access_key="access",
            qiniu_secret_key="secret",
            qiniu_domain="https://cdn-paper.yixun.club",
            qiniu_download_expires=3600,
        ),
    )

    url = build_qiniu_private_download_url("paper/task-id/论文 测试.docx")

    assert url.startswith("https://cdn-paper.yixun.club/paper/task-id/")
    assert "%E8%AE%BA%E6%96%87%20%E6%B5%8B%E8%AF%95.docx" in url
    assert "e=" in url
    assert "token=" in url


def test_order_list_item_does_not_expose_download_url() -> None:
    item = order_workflow._paper_order_list_item(
        SimpleNamespace(
            id=1,
            order_sn="AP001",
            title="测试论文",
            status="completed",
            cost_points=200,
            paid_points=200,
            refunded_points=0,
            last_error="",
            created_at=SimpleNamespace(isoformat=lambda: "2026-06-04T13:45:43+08:00"),
            paid_at=None,
            completed_at=SimpleNamespace(isoformat=lambda: "2026-06-04T13:49:18+08:00"),
        )
    )

    assert item.has_file == 1
    assert item.download_url is None


def test_run_paid_paper_order_skips_when_order_start_was_claimed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    claimed_order_ids: list[int] = []

    async def fake_mark_generating_if_paid(order_id: int, task_id: str) -> None:
        assert task_id
        claimed_order_ids.append(order_id)
        return None

    async def fake_run_generate_task(*args: object, **kwargs: object) -> None:
        raise AssertionError("重复后台任务不应该再次启动论文生成")

    monkeypatch.setattr(PaperOrderService, "mark_generating_if_paid", fake_mark_generating_if_paid)
    monkeypatch.setattr(order_workflow, "run_generate_task", fake_run_generate_task)

    asyncio.run(order_workflow.run_paid_paper_order(123))

    assert claimed_order_ids == [123]


@pytest.mark.parametrize(
    ("error_type", "message"),
    [
        ("provider_quota", "生成服务暂时不可用，本次扣除积分已退回，请稍后重试或联系管理员"),
        ("provider_config", "生成服务配置异常，本次扣除积分已退回，请联系管理员处理"),
    ],
)
def test_provider_failure_refunds_order_with_sanitized_message(
    monkeypatch: pytest.MonkeyPatch,
    error_type: str,
    message: str,
) -> None:
    refund_calls: list[tuple[int, str]] = []
    order = SimpleNamespace(id=7)

    async def fake_refund_failed_order_points(order_id: int, reason: str) -> SimpleNamespace:
        refund_calls.append((order_id, reason))
        return SimpleNamespace(id=order_id, status="failed", last_error=reason)

    monkeypatch.setattr(PaperOrderService, "refund_failed_order_points", fake_refund_failed_order_points)

    result = asyncio.run(
        PaperOrderService.mark_from_task_status(
            order,
            {
                "status": "failed",
                "error_type": error_type,
                "message": message,
                "internal_error": "用户额度不足, 剩余额度: ¥-0.499362",
            },
        )
    )

    assert result.last_error == message
    assert refund_calls == [(7, message)]
