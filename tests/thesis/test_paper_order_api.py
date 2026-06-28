import asyncio
from collections.abc import Generator
from types import SimpleNamespace
from typing import cast

import pytest
from fastapi.testclient import TestClient

from api.dependencies.api_token import get_api_token_or_jwt_user
from app import app
from models.paper import PaperOrder
from services.thesis.business import order_workflow
from services.thesis.business.order_service import PaperOrderService
from services.thesis.storage.qiniu_storage import build_qiniu_private_download_url


@pytest.fixture
def client() -> Generator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_paper_order_routes_are_registered() -> None:
    routes = {str(getattr(route, "path", "")) for route in app.routes}
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
        "services.thesis.storage.qiniu_storage.get_settings",
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
        cast(
            PaperOrder,
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
            ),
        )
    )

    assert item.has_file == 1
    assert item.download_url is None


def test_normalize_generate_input_preserves_direct_cover_fields() -> None:
    order = cast(
        PaperOrder,
        SimpleNamespace(
            title="测试论文",
            outline_json=[
                {
                    "chapter": "绪论",
                    "sections": [
                        {"name": "研究背景", "abstract": "背景"},
                    ],
                }
            ],
            config_form={
                "target_word_count": 12_000,
                "codetype": "Python",
                "wxquote": "标注",
                "language": "是",
                "wxnum": 35,
                "author": "张三",
                "advisor": "李四 教授",
                "degree_type": "硕士",
                "major": "软件工程",
                "school": "计算机学院",
                "year_month": "2026年06月",
                "student_id": "20260001",
                "student_class": "软件工程1班",
            },
        ),
    )

    normalized = PaperOrderService.normalize_generate_input(order)

    assert normalized.target_word_count == 12_000
    assert normalized.codetype == "Python"
    assert normalized.language == "是"
    assert normalized.wxnum == 35
    assert normalized.author == "张三"
    assert normalized.advisor == "李四 教授"
    assert normalized.degree_type == "硕士"
    assert normalized.major == "软件工程"
    assert normalized.school == "计算机学院"
    assert normalized.year_month == "2026年06月"
    assert normalized.student_id == "20260001"
    assert normalized.student_class == "软件工程1班"


def test_run_paid_paper_order_delegates_to_generation_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, int]] = []

    async def fake_create_order_generation_task(order_id: int) -> SimpleNamespace:
        calls.append(("create", order_id))
        return SimpleNamespace(id=456)

    async def fake_run_generation_task(generation_task_id: int) -> None:
        calls.append(("run", generation_task_id))

    monkeypatch.setattr(PaperOrderService, "create_order_generation_task", fake_create_order_generation_task)
    monkeypatch.setattr(order_workflow, "run_generation_task", fake_run_generation_task)

    asyncio.run(order_workflow.run_paid_paper_order(123))

    assert calls == [("create", 123), ("run", 456)]


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
    refund_calls: list[tuple[int, str, str]] = []
    order = cast(PaperOrder, SimpleNamespace(id=7))

    async def fake_refund_failed_order_points(
        order_id: int,
        reason: str,
        failure_type: str = "generation_error",
    ) -> SimpleNamespace:
        refund_calls.append((order_id, reason, failure_type))
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
    assert refund_calls == [(7, message, error_type)]


def test_generation_failure_schedules_retry_before_final_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    retry_calls: list[tuple[int, str]] = []
    order = cast(PaperOrder, SimpleNamespace(id=7))
    retried_order = SimpleNamespace(id=7, status="paid", last_error="生成失败，将自动重试 1/2")

    async def fake_schedule_order_retry_if_possible(order_id: int, data: dict) -> SimpleNamespace:
        retry_calls.append((order_id, str(data.get("message"))))
        return retried_order

    monkeypatch.setattr(PaperOrderService, "schedule_order_retry_if_possible", fake_schedule_order_retry_if_possible)

    result = asyncio.run(
        PaperOrderService.mark_from_task_status(
            order,
            {
                "status": "failed",
                "error_type": "generation_error",
                "message": "生成失败，请稍后重试或联系管理员",
            },
        )
    )

    assert result is retried_order
    assert retry_calls == [(7, "生成失败，请稍后重试或联系管理员")]


def test_generation_failure_refunds_order_after_retry_exhausted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    refund_calls: list[tuple[int, str, str]] = []
    order = cast(PaperOrder, SimpleNamespace(id=7))

    async def fake_schedule_order_retry_if_possible(order_id: int, data: dict) -> None:
        assert order_id == 7
        assert data["error_type"] == "generation_error"
        return None

    async def fake_refund_failed_order_points(
        order_id: int,
        reason: str,
        failure_type: str = "generation_error",
    ) -> SimpleNamespace:
        refund_calls.append((order_id, reason, failure_type))
        return SimpleNamespace(id=order_id, status="failed", last_error=reason)

    monkeypatch.setattr(PaperOrderService, "schedule_order_retry_if_possible", fake_schedule_order_retry_if_possible)
    monkeypatch.setattr(PaperOrderService, "refund_failed_order_points", fake_refund_failed_order_points)

    result = asyncio.run(
        PaperOrderService.mark_from_task_status(
            order,
            {
                "status": "failed",
                "error_type": "generation_error",
                "message": "生成失败，请稍后重试或联系管理员",
            },
        )
    )

    assert result.status == "failed"
    assert refund_calls == [(7, "生成失败，请稍后重试或联系管理员", "generation_error")]
