"""四类文档文件名、存储链接和历史下载契约。"""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import unquote

import pytest

from api.v1 import thesis, thesis_material
from models.user import User
from services.thesis.document.utils import build_document_filename
from services.thesis.generation.task_service import _download_path_from_status
from services.thesis.storage import document_storage, local_storage
from services.thesis_material import workflow


# 文件名在生成路径、存储 key 和下载响应之间必须一致。
@pytest.mark.parametrize("document_type,label", [
    ("thesis", "论文"), ("proposal_report", "开题报告"),
    ("literature_review", "文献综述"), ("task_book", "任务书"),
])
async def test_document_filename_storage_and_download_are_consistent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, document_type: str, label: str,
) -> None:
    """四类新文件实际落盘后，其 URL、远端 key 和响应附件名一致。"""
    monkeypatch.chdir(tmp_path)
    settings = SimpleNamespace(STORAGE_PROVIDER="local", STORAGE_OBJECT_PREFIX="paper", public_base_url="https://paper.example.test")
    monkeypatch.setattr(document_storage, "get_settings", lambda: settings)
    monkeypatch.setattr(local_storage, "get_settings", lambda: settings)
    name = build_document_filename("测试标题", document_type, "task123")
    assert name == f"测试标题-{label}-task123.docx"
    assert build_document_filename("测试标题", document_type, "task123") == name
    assert build_document_filename("测试标题", document_type, "task456") != name
    path = tmp_path / "public/output/task123" / name
    path.parent.mkdir(parents=True)
    path.write_bytes(b"test document")
    stored = await document_storage.store_document(str(path), "task123")
    assert unquote(stored.download_url).endswith("/" + name)
    assert document_storage.build_remote_object_key(path, "task123") == f"paper/task123/{name}"
    assert document_storage.build_download_url("local", stored.file_key) == stored.download_url
    if document_type == "thesis":
        monkeypatch.setattr(thesis.generation_task, "get_download_path_for_user", AsyncMock(return_value=path))
        response = await thesis.download_document("task123", User(id=1))
    else:
        monkeypatch.setattr(thesis_material.workflow, "get_download_path", AsyncMock(return_value=path))
        response = await thesis_material.download_task("task123", User(id=1))
    assert response.filename == name
    assert name in unquote(response.headers["content-disposition"])


# 新命名规则不能反推或替换历史任务保存的路径。
@pytest.mark.parametrize("name", ["旧论文-oldtask.docx", "旧材料-proposal_report.docx", "旧材料-literature_review.docx", "旧材料-task_book.docx"])
async def test_historical_download_keeps_saved_filename(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str,
) -> None:
    """历史文件仍可通过原始状态路径和附件名称下载。"""
    path = tmp_path / name
    path.write_bytes(b"historical document")
    assert _download_path_from_status({"status": "completed", "docx_path": str(path)}) == path
    monkeypatch.setattr(thesis_material.workflow, "get_download_path", AsyncMock(return_value=path))
    response = await thesis_material.download_task("oldtask", User(id=1))
    assert response.filename == name
    assert name in unquote(response.headers["content-disposition"])


# 用户标题里的控制字符和路径符号不得成为文件名的一部分。
def test_document_filename_sanitizes_title_and_preserves_suffix() -> None:
    """长标题被截断，中文类型、任务 ID 和扩展名始终保留。"""
    name = build_document_filename('../题目/\\:*?"<>|\r\n' + "长" * 150, "task_book", "abc123")
    assert name.endswith("-任务书-abc123.docx")
    assert all(character not in name for character in '/\\:*?"<>|\r\n')
    assert ".." not in name
    assert len(name) < 120
    assert len(name.encode("utf-8")) <= 255


# 材料状态丢失时，持久化的历史本地 key 仍能解析为原文件。
async def test_historical_material_download_uses_persisted_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """覆盖历史材料原始状态路径及本地存储 key 兜底。"""
    monkeypatch.chdir(tmp_path)
    key = "output/oldtask/旧材料-task_book.docx"
    path = tmp_path / "public" / key
    path.parent.mkdir(parents=True)
    path.write_bytes(b"historical document")
    task = SimpleNamespace(status="completed", local_file_key=key)
    monkeypatch.setattr(workflow, "_owned_task", AsyncMock(return_value=task))
    status = AsyncMock(return_value={"docx_path": str(path)})
    monkeypatch.setattr(workflow.status_store, "read_status_async", status)
    assert await workflow.get_download_path(User(id=1), "oldtask") == path
    status.return_value = None
    assert (await workflow.get_download_path(User(id=1), "oldtask")).resolve() == path
