import json
from pathlib import Path

import pytest

from services.thesis.generation import status_store


class _FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        del ex
        self.values[key] = value

    async def get(self, key: str) -> str | None:
        return self.values.get(key)


class _BrokenRedis:
    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        del key, value, ex
        raise RuntimeError("redis down")

    async def get(self, key: str) -> str | None:
        del key
        raise RuntimeError("redis down")


@pytest.mark.asyncio
async def test_async_status_store_reads_from_redis(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fake_redis = _FakeRedis()
    task_id = "redisstatus1"
    monkeypatch.setattr(status_store, "OUTPUT_ROOT", tmp_path)
    monkeypatch.setattr(status_store.redis_module, "redis_client", fake_redis)

    await status_store.write_status_async(task_id, "pending", message="running")
    (tmp_path / task_id / status_store.STATUS_FILE_NAME).unlink()

    stored = await status_store.read_status_async(task_id)

    assert stored == {"task_id": task_id, "status": "pending", "message": "running"}


@pytest.mark.asyncio
async def test_async_status_store_falls_back_to_file_when_redis_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    task_id = "filestatus1"
    status_dir = tmp_path / task_id
    status_dir.mkdir(parents=True)
    (status_dir / status_store.STATUS_FILE_NAME).write_text(
        json.dumps({"task_id": task_id, "status": "completed", "message": "done"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(status_store, "OUTPUT_ROOT", tmp_path)
    monkeypatch.setattr(status_store.redis_module, "redis_client", _BrokenRedis())

    stored = await status_store.read_status_async(task_id)

    assert stored == {"task_id": task_id, "status": "completed", "message": "done"}
