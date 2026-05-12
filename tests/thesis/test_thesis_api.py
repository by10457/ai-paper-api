from pathlib import Path
from urllib.parse import unquote
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app import app
from services.thesis import generation_task, status_store


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(status_store, "OUTPUT_ROOT", tmp_path)
    with TestClient(app) as test_client:
        yield test_client


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
    async def fake_run_generate(
        task_id: str,
        title: str,
        outline: str,
        cover_kwargs: dict | None = None,
        codetype: str = "否",
        wxquote: str = "标注",
        language: str = "否",
        wxnum: int = 25,
    ) -> None:
        assert task_id
        assert title
        assert outline
        assert cover_kwargs is not None
        assert isinstance(cover_kwargs, dict)
        assert cover_kwargs["target_word_count"] == 12000
        assert cover_kwargs["student_id"] == "20260001"
        assert cover_kwargs["student_class"] == "软件工程1班"

    monkeypatch.setattr(generation_task, "run_generate_task", fake_run_generate)

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
            "target_word_count": 12000,
            "student_id": "20260001",
            "student_class": "软件工程1班",
        },
    )

    assert response.status_code == 200
    task_id = response.json()["task_id"]

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
