"""论文生成任务状态存储。

状态优先写入 Redis，便于多进程和后续多机部署共享轮询结果；本地 status.json
仍作为兜底，避免 Redis 临时不可用时影响单机流程。
"""

import asyncio
import json
from pathlib import Path
from typing import Any, cast

from core import redis as redis_module
from core.config import get_settings
from core.logger import logger

OUTPUT_ROOT = Path(get_settings().thesis_output_root)
STATUS_FILE_NAME = "status.json"
STATUS_KEY_PREFIX = "ai-paper:thesis:status:"
STATUS_TTL_SECONDS = 7 * 24 * 60 * 60
TERMINAL_STATUSES = {"completed", "failed"}


def status_path(task_id: str) -> Path:
    """返回任务状态文件路径。"""

    return OUTPUT_ROOT / task_id / STATUS_FILE_NAME


def status_key(task_id: str) -> str:
    """返回 Redis 中保存任务状态的 key。"""

    return f"{STATUS_KEY_PREFIX}{task_id}"


def write_status(task_id: str, status: str, **extra: Any) -> None:
    """写入本地任务状态文件，保留给同步测试和 Redis 兜底使用。"""

    _write_file_status(task_id, _build_status_data(task_id, status, extra))


def read_status(task_id: str) -> dict[str, Any] | None:
    """读取本地任务状态文件，不存在时返回 None。"""

    return _read_file_status(task_id)


async def write_status_async(task_id: str, status: str, **extra: Any) -> None:
    """写入任务状态，Redis 优先，本地文件兜底。"""

    data = _build_status_data(task_id, status, extra)
    await _write_redis_status(task_id, data)
    await asyncio.to_thread(_write_file_status, task_id, data)


async def read_status_async(task_id: str) -> dict[str, Any] | None:
    """读取任务状态，优先读取 Redis，失败或不存在时读取本地文件。"""

    redis_data = await _read_redis_status(task_id)
    file_data = await asyncio.to_thread(_read_file_status, task_id)
    if redis_data is None:
        return file_data
    if _should_prefer_file_status(redis_data, file_data):
        await _write_redis_status(task_id, cast(dict[str, Any], file_data))
        return file_data
    return redis_data


def _build_status_data(task_id: str, status: str, extra: dict[str, Any]) -> dict[str, Any]:
    """构造统一的任务状态字典。"""

    return {"task_id": task_id, "status": status, **extra}


def _write_file_status(task_id: str, data: dict[str, Any]) -> None:
    """写入本地任务状态文件。"""

    path = status_path(task_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _read_file_status(task_id: str) -> dict[str, Any] | None:
    """读取本地任务状态文件。"""

    path = status_path(task_id)
    if not path.exists():
        return None
    return cast("dict[str, Any]", json.loads(path.read_text(encoding="utf-8")))


def _should_prefer_file_status(
    redis_data: dict[str, Any],
    file_data: dict[str, Any] | None,
) -> bool:
    """当本地文件已进入终态而 Redis 仍是中间态时，用文件修正 Redis。"""

    if file_data is None:
        return False
    redis_status = str(redis_data.get("status") or "")
    file_status = str(file_data.get("status") or "")
    return redis_status not in TERMINAL_STATUSES and file_status in TERMINAL_STATUSES


async def _write_redis_status(task_id: str, data: dict[str, Any]) -> None:
    """写入 Redis；Redis 未初始化或写入失败时安静降级。"""

    client = redis_module.redis_client
    if client is None:
        return
    try:
        await client.set(
            status_key(task_id),
            json.dumps(data, ensure_ascii=False),
            ex=STATUS_TTL_SECONDS,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("写入 Redis 任务状态失败，已降级到本地文件: task_id={}, err={}", task_id, exc)


async def _read_redis_status(task_id: str) -> dict[str, Any] | None:
    """读取 Redis 任务状态；读取失败时返回 None 交给本地文件兜底。"""

    client = redis_module.redis_client
    if client is None:
        return None
    try:
        payload = await client.get(status_key(task_id))
    except Exception as exc:  # noqa: BLE001
        logger.debug("读取 Redis 任务状态失败，已降级到本地文件: task_id={}, err={}", task_id, exc)
        return None
    if not payload:
        return None
    try:
        return cast("dict[str, Any]", json.loads(str(payload)))
    except json.JSONDecodeError:
        logger.debug("Redis 任务状态 JSON 解析失败: task_id={}", task_id)
        return None
