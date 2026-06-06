import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

import services.thesis.business.order_callback as callback_service
import services.thesis.storage.document_storage as document_storage
import services.thesis.storage.local_storage as local_storage
from services.thesis.business import order_workflow


def _settings(**overrides: object) -> SimpleNamespace:
    defaults = {
        "PUBLIC_BASE_URL": "https://paper.example.com",
        "public_base_url": "https://paper.example.com",
        "STORAGE_PROVIDER": "local",
        "STORAGE_OBJECT_PREFIX": "paper",
        "STORAGE_DOWNLOAD_EXPIRES": 3600,
        "QINIU_ACCESS_KEY": "",
        "QINIU_SECRET_KEY": "",
        "QINIU_BUCKET": "",
        "QINIU_DOMAIN": "",
        "QINIU_DOWNLOAD_EXPIRES": 3600,
        "qiniu_access_key": "",
        "qiniu_secret_key": "",
        "qiniu_bucket": "",
        "qiniu_domain": "",
        "qiniu_download_expires": 3600,
        "MINIO_ENDPOINT": "",
        "MINIO_ACCESS_KEY": "",
        "MINIO_SECRET_KEY": "",
        "MINIO_BUCKET": "",
        "MINIO_SECURE": False,
        "MINIO_DOMAIN": "",
        "COS_SECRET_ID": "",
        "COS_SECRET_KEY": "",
        "COS_BUCKET": "",
        "COS_REGION": "",
        "COS_DOMAIN": "",
        "COS_ACCESS_POLICY": "PRIVATE",
        "COS_UPLOAD_ALLOW_PREFIX": "*",
        "paper_callback_url": "",
        "paper_callback_secret": "",
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def test_store_document_local_records_fallback_key_and_url(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(document_storage, "get_settings", lambda: _settings())
    monkeypatch.setattr(local_storage, "get_settings", lambda: _settings())
    output = tmp_path / "public/output/thesis/测试论文-task123.docx"
    output.parent.mkdir(parents=True)
    output.write_bytes(b"docx")

    stored = asyncio.run(document_storage.store_document(str(output), "task123"))

    assert stored.storage_provider == "local"
    assert stored.file_key == "output/thesis/测试论文-task123.docx"
    assert stored.local_file_key == "output/thesis/测试论文-task123.docx"
    assert stored.download_url == "https://paper.example.com/output/thesis/%E6%B5%8B%E8%AF%95%E8%AE%BA%E6%96%87-task123.docx"


def test_build_remote_object_key_uses_task_folder_and_filename(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        document_storage,
        "get_settings",
        lambda: _settings(STORAGE_OBJECT_PREFIX="paper-output"),
    )

    object_key = document_storage.build_remote_object_key(tmp_path / "基于AI的系统-taskabc.docx", "taskabc")

    assert object_key == "paper-output/taskabc/基于AI的系统-taskabc.docx"


def test_order_download_url_regenerates_remote_signed_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        document_storage,
        "build_download_url",
        lambda provider, file_key, local_file_key: f"https://fresh.example.com/{provider}/{file_key}",
    )
    order = SimpleNamespace(
        status="completed",
        storage_provider="qiniu",
        file_key="paper/task/doc.docx",
        local_file_key="output/thesis/doc.docx",
        download_url="https://expired.example.com/doc.docx",
    )

    assert order_workflow._build_order_download_url(order) == "https://fresh.example.com/qiniu/paper/task/doc.docx"


def test_order_download_url_keeps_manual_link() -> None:
    order = SimpleNamespace(
        status="completed",
        storage_provider="manual",
        file_key="manual-key",
        local_file_key="",
        download_url="https://manual.example.com/doc.docx",
    )

    assert order_workflow._build_order_download_url(order) == "https://manual.example.com/doc.docx"


def test_notify_callback_sends_storage_and_local_fallback_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: dict[str, object] = {}
    monkeypatch.setattr(callback_service, "get_settings", lambda: _settings())

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

    class FakeAsyncClient:
        def __init__(self, timeout: float):
            self.timeout = timeout

        async def __aenter__(self) -> "FakeAsyncClient":
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def post(self, url: str, json: dict[str, str], headers: dict[str, str] | None) -> FakeResponse:
            sent["url"] = url
            sent["json"] = json
            sent["headers"] = headers
            return FakeResponse()

    monkeypatch.setattr(callback_service.httpx, "AsyncClient", FakeAsyncClient)

    asyncio.run(
        callback_service.notify_callback(
            "task123",
            file_key="paper/task123/doc.docx",
            status="completed",
            callback_url="https://biz.example.com/callback",
            download_url="https://cdn.example.com/doc.docx",
            storage_provider="minio",
            local_file_key="output/thesis/doc.docx",
            local_download_url="https://paper.example.com/output/thesis/doc.docx",
        )
    )

    assert sent["url"] == "https://biz.example.com/callback"
    assert sent["headers"] is None
    assert sent["json"] == {
        "task_id": "task123",
        "file_key": "paper/task123/doc.docx",
        "download_url": "https://cdn.example.com/doc.docx",
        "storage_provider": "minio",
        "local_file_key": "output/thesis/doc.docx",
        "local_download_url": "https://paper.example.com/output/thesis/doc.docx",
        "status": "completed",
        "error_msg": "",
    }
