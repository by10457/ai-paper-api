"""论文生成阶段进度发布。

活跃阶段状态写入 Redis/status_store，便于 Web SSE 实时读取；关键阶段
同步落到 paper_generation_tasks，避免高频数据库写入。
"""

from __future__ import annotations

from contextlib import AbstractContextManager
from datetime import datetime
from typing import Any

from tortoise import timezone

from core.logger import logger
from models.paper import PaperGenerationTask
from services.thesis.generation import status_store
from services.thesis.generation.runtime_context import (
    GenerationRuntimeContext,
    get_runtime_context,
    use_runtime_context,
)

MAX_PROCESS_EVENTS = 80

STAGE_PROGRESS = {
    "queued": 2,
    "started": 5,
    "references": 18,
    "fulltext": 42,
    "abstracts": 62,
    "figures": 76,
    "document": 90,
    "storage": 96,
    "callback": 98,
    "completed": 100,
    "failed": 100,
}


async def publish_progress(
    task_id: str,
    stage: str,
    message: str,
    *,
    progress: int | None = None,
    status: str = "pending",
    **extra: Any,
) -> None:
    """发布任务进度，并把阶段快照同步到任务表。"""

    resolved_progress = progress if progress is not None else STAGE_PROGRESS.get(stage, 0)
    existing = await status_store.read_status_async(task_id)
    events = _append_process_event(existing, stage, message, resolved_progress, status, extra)
    payload = {
        "message": message,
        "stage": stage,
        "progress": resolved_progress,
        "events": events,
        **extra,
    }
    await status_store.write_status_async(task_id, status, **payload)
    if get_runtime_context().generation_task_id is not None:
        try:
            await _update_generation_task(task_id, stage, resolved_progress, events, status, message, extra)
        except Exception as exc:  # noqa: BLE001
            logger.debug("同步论文生成任务阶段到数据库失败: task_id={}, stage={}, err={}", task_id, stage, exc)


async def record_process_detail(stage: str, message: str, **details: Any) -> None:
    """记录生成过程中的关键业务数据，不改变当前任务状态。"""

    ctx = get_runtime_context()
    if not ctx.task_id:
        return

    existing = await status_store.read_status_async(ctx.task_id)
    status = str(existing.get("status") or "pending") if existing else "pending"
    progress = int(existing.get("progress") or STAGE_PROGRESS.get(stage, 0)) if existing else STAGE_PROGRESS.get(stage, 0)
    events = _append_process_event(existing, stage, message, progress, status, details, event_type="detail")
    payload = {
        **_status_extra(existing),
        "events": events,
    }
    await status_store.write_status_async(ctx.task_id, status, **payload)

    if ctx.generation_task_id is not None:
        try:
            await _update_generation_task(ctx.task_id, stage, progress, events, status, message, details)
        except Exception as exc:  # noqa: BLE001
            logger.debug("同步论文生成过程详情到数据库失败: task_id={}, stage={}, err={}", ctx.task_id, stage, exc)


def stage_context(stage: str) -> AbstractContextManager[GenerationRuntimeContext]:
    """返回阶段上下文管理器，供 LLM 日志自动记录当前阶段。"""

    return use_runtime_context(stage=stage)


def _status_extra(existing: dict[str, Any] | None) -> dict[str, Any]:
    """返回可安全传给 write_status_async 的状态扩展字段。"""

    if not existing:
        return {}
    return {key: value for key, value in existing.items() if key not in {"status", "task_id"}}


def _append_process_event(
    existing: dict[str, Any] | None,
    stage: str,
    message: str,
    progress: int,
    status: str,
    details: dict[str, Any] | None = None,
    *,
    event_type: str = "stage",
) -> list[dict[str, Any]]:
    events = []
    if existing and isinstance(existing.get("events"), list):
        events = list(existing["events"])
    now = timezone.now()
    if event_type == "stage" and events:
        previous = events[-1]
        if previous.get("type") == "stage" and not previous.get("completed_at"):
            previous["completed_at"] = now.isoformat()
            previous_started_at = previous.get("started_at") or previous.get("time")
            previous["duration_ms"] = _duration_ms(previous_started_at, now)
    event = {
        "type": event_type,
        "stage": stage,
        "message": message,
        "progress": progress,
        "status": status,
        "time": now.isoformat(),
        "started_at": now.isoformat(),
    }
    if details:
        event["details"] = details
    if status in {"completed", "failed"}:
        event["completed_at"] = now.isoformat()
        event["duration_ms"] = 0
    if event_type == "detail" or not events or events[-1].get("stage") != stage or events[-1].get("message") != message:
        events.append(event)
    return events[-MAX_PROCESS_EVENTS:]


def _duration_ms(started_at: object, ended_at: Any) -> int:
    if not isinstance(started_at, str):
        return 0
    try:
        started = datetime.fromisoformat(started_at)
    except ValueError:
        return 0
    return max(int((ended_at - started).total_seconds() * 1000), 0)


async def _update_generation_task(
    task_id: str,
    stage: str,
    progress: int,
    events: list[dict[str, Any]],
    status: str,
    message: str,
    extra: dict[str, Any],
) -> None:
    generation_task = await PaperGenerationTask.filter(task_id=task_id).first()
    if generation_task is None:
        return

    update_data: dict[str, Any] = {
        "current_stage": stage,
        "progress": progress,
        "process_events": events,
        "updated_at": timezone.now(),
    }
    if extra:
        metadata = generation_task.process_metadata if isinstance(generation_task.process_metadata, dict) else {}
        stage_items = metadata.get(stage)
        if isinstance(stage_items, list):
            stage_items.append(extra)
        elif stage_items:
            stage_items = [stage_items, extra]
        else:
            stage_items = [extra]
        metadata[stage] = stage_items
        update_data["process_metadata"] = metadata
    if status in {"completed", "failed"}:
        update_data["status"] = status
        update_data["completed_at"] = timezone.now()
        update_data["last_error"] = "" if status == "completed" else message[:500]
        update_data["result_summary"] = extra or None
    await PaperGenerationTask.filter(id=generation_task.id).update(**update_data)


__all__ = ["publish_progress", "record_process_detail", "stage_context"]
