from pathlib import Path
from types import SimpleNamespace
from urllib.parse import unquote
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from api.dependencies.api_token import get_api_token_or_jwt_user
from app import app
from services.thesis.business.order_service import PaperOrderService
from services.thesis.generation import status_store
from services.thesis.generation import task_service as generation_task


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    async def fake_current_user() -> SimpleNamespace:
        return SimpleNamespace(id=1, username="demo", points=1000, is_disabled=False)

    app.dependency_overrides[get_api_token_or_jwt_user] = fake_current_user
    monkeypatch.setattr(status_store, "OUTPUT_ROOT", tmp_path)
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_thesis_routes_are_registered() -> None:
    routes = {route.path for route in app.routes}
    assert "/api/v1/thesis/outline" in routes
    assert "/api/v1/thesis/generate" in routes
    assert "/api/v1/thesis/status/{task_id}" in routes
    assert "/api/v1/thesis/download/{task_id}" in routes


def test_outline_success(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_generate_outline(
        title: str,
        target_word_count: int,
        codetype: str,
        language: str,
        three_level: bool,
        aboutmsg: str,
    ) -> dict:
        return {
            "outline": [
                {
                    "chapter": "绪论",
                    "sections": [
                        {"name": "研究背景", "abstract": "介绍研究背景。"},
                    ],
                }
            ],
            "abstract": f"{title}摘要",
            "keywords": "关键词1,关键词2",
        }

    monkeypatch.setattr(generation_task, "load_generate_outline", lambda: fake_generate_outline)

    response = client.post(
        "/api/v1/thesis/outline",
        json={"title": "基于大模型的论文自动生成系统设计"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["title"] == "基于大模型的论文自动生成系统设计"
    assert payload["outline"][0]["chapter"] == "绪论"


def test_outline_title_too_short_returns_422(client: TestClient) -> None:
    response = client.post("/api/v1/thesis/outline", json={"title": "a"})
    assert response.status_code == 422


def test_generate_and_status_flow(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    task_create_calls: list[tuple[int, str]] = []
    enqueue_calls: list[int] = []

    async def fake_create_direct_generate_task(
        user: SimpleNamespace,
        *,
        task_id: str,
        title: str,
        request_payload: dict[str, object],
        idempotency_key: str | None,
    ) -> tuple[SimpleNamespace, bool]:
        assert request_payload["title"] == title
        assert idempotency_key == "wxy-paper-order-1"
        task_create_calls.append((user.id, title))
        assert task_id
        return SimpleNamespace(id=11, task_id=task_id, status="paid"), True

    async def fake_enqueue_generation_task(
        generation_task_id: int,
        delay_seconds: int = 0,
    ) -> bool:
        assert generation_task_id == 11
        assert delay_seconds == 0
        enqueue_calls.append(generation_task_id)
        return True

    monkeypatch.setattr(PaperOrderService, "create_direct_generate_task", fake_create_direct_generate_task)
    monkeypatch.setattr(generation_task, "enqueue_generation_task", fake_enqueue_generation_task)

    response = client.post(
        "/api/v1/thesis/generate",
        headers={"Idempotency-Key": "wxy-paper-order-1"},
        json={
            "title": "测试论文",
            "outline_json": [
                {
                    "chapter": "绪论",
                    "sections": [
                        {"name": "研究背景", "abstract": "正文" * 30},
                    ],
                }
            ],
            "target_word_count": 12000,
            "student_id": "20260001",
            "student_class": "软件工程1班",
        },
    )

    assert response.status_code == 200
    task_id = response.json()["task_id"]
    assert task_create_calls == [(1, "测试论文")]
    assert enqueue_calls == [11]

    pending = client.get(f"/api/v1/thesis/status/{task_id}")
    assert pending.status_code == 200
    assert pending.json()["status"] == "pending"

    status_store.write_status(
        task_id,
        "completed",
        message="论文生成完成",
        figure_count=3,
        mermaid_count=2,
        chart_count=1,
        ai_image_count=1,
        fallback_count=0,
        fulltext_char_count=8200,
        truncation_warning=False,
    )
    completed = client.get(f"/api/v1/thesis/status/{task_id}")
    assert completed.status_code == 200
    payload = completed.json()
    assert payload["status"] == "completed"
    assert payload["figure_count"] == 3
    assert payload["mermaid_count"] == 2
    assert payload["chart_count"] == 1
    assert payload["ai_image_count"] == 1


def test_generate_reuses_idempotent_generation_task(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_create_direct_generate_task(
        user: SimpleNamespace,
        *,
        task_id: str,
        title: str,
        request_payload: dict[str, object],
        idempotency_key: str | None,
    ) -> tuple[SimpleNamespace, bool]:
        del user, task_id, title, request_payload
        assert idempotency_key == "wxy-paper-order-1"
        return SimpleNamespace(id=11, task_id="existing-task", status="generating"), False

    async def fake_enqueue_generation_task(generation_task_id: int, delay_seconds: int = 0) -> bool:
        del delay_seconds
        raise AssertionError(f"幂等复用任务不应该重复启动生成: {generation_task_id}")

    monkeypatch.setattr(PaperOrderService, "create_direct_generate_task", fake_create_direct_generate_task)
    monkeypatch.setattr(generation_task, "enqueue_generation_task", fake_enqueue_generation_task)

    response = client.post(
        "/api/v1/thesis/generate",
        headers={"Idempotency-Key": "wxy-paper-order-1"},
        json={
            "title": "测试论文",
            "outline_json": [
                {
                    "chapter": "绪论",
                    "sections": [
                        {"name": "研究背景", "abstract": "正文" * 30},
                    ],
                }
            ],
        },
    )

    assert response.status_code == 200
    assert response.json()["task_id"] == "existing-task"


def test_generate_invalid_target_word_count_returns_422(client: TestClient) -> None:
    response = client.post(
        "/api/v1/thesis/generate",
        json={
            "title": "测试论文",
            "outline_json": [
                {
                    "chapter": "绪论",
                    "sections": [
                        {"name": "研究背景", "abstract": "正文" * 30},
                    ],
                }
            ],
            "target_word_count": "invalid",
        },
    )

    assert response.status_code == 422


def test_status_utils_roundtrip(client: TestClient) -> None:
    task_id = uuid4().hex[:12]
    status_store.write_status(task_id, "pending", message="running")
    stored = status_store.read_status(task_id)

    assert stored is not None
    assert stored["task_id"] == task_id
    assert stored["status"] == "pending"
    assert stored["message"] == "running"


def test_download_pending_returns_409(client: TestClient) -> None:
    task_id = uuid4().hex[:12]
    status_store.write_status(task_id, "pending", message="正在生成论文...")

    response = client.get(f"/api/v1/thesis/download/{task_id}")

    assert response.status_code == 409


def test_download_nonexistent_task_returns_404(client: TestClient) -> None:
    response = client.get(f"/api/v1/thesis/download/{uuid4().hex[:12]}")
    assert response.status_code == 404


def test_download_completed_returns_docx(client: TestClient, tmp_path: Path) -> None:
    task_id = uuid4().hex[:12]
    output_dir = tmp_path / task_id
    output_dir.mkdir(parents=True, exist_ok=True)
    docx_path = output_dir / "论文_测试.docx"
    docx_path.write_bytes(b"fake docx payload")

    status_store.write_status(
        task_id,
        "completed",
        message="论文生成完成",
        docx_path=str(docx_path),
    )

    response = client.get(f"/api/v1/thesis/download/{task_id}")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    disposition = response.headers["content-disposition"]
    assert "filename*=" in disposition
    assert unquote(disposition).endswith("论文_测试.docx")
