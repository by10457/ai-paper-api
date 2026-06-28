"""论文大纲与正文生成任务编排。"""

import logging
import uuid
from collections.abc import Awaitable, Callable
from importlib import import_module
from pathlib import Path
from typing import Any, cast

from fastapi import HTTPException

from llm.client import is_provider_config_error, is_provider_quota_error
from models.paper import PaperGenerationTask
from models.user import User
from schemas.thesis import (
    GenerateRequest,
    GenerateSubmitResponse,
    OutlineChapter,
    OutlineRequest,
    OutlineResponse,
    TaskStatusResponse,
)
from services.thesis.business.order_service import PaperOrderService
from services.thesis.generation import status_store
from services.thesis.generation.paper_queue import enqueue_generation_task
from services.thesis.generation.progress import publish_progress
from services.thesis.generation.runtime_context import use_runtime_context

logger = logging.getLogger(__name__)

GenerateOutlineCallable = Callable[..., Awaitable[dict[str, Any]]]
GenerateDocumentCallable = Callable[..., Awaitable[Any]]


def create_task_id() -> str:
    """创建对外暴露的短任务 ID。"""

    return uuid.uuid4().hex[:12]


def load_generate_outline() -> GenerateOutlineCallable:
    """延迟加载大纲服务，避免应用启动阶段过早初始化 LLM 链。"""

    try:
        module = import_module("services.thesis.content.outline_service")
        return cast(GenerateOutlineCallable, module.generate_outline)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError("论文大纲服务未就绪") from exc


def load_generate_document() -> GenerateDocumentCallable:
    """延迟加载正文生成服务，降低测试和路由导入成本。"""

    try:
        module = import_module("services.thesis.generation.pipeline")
        return cast(GenerateDocumentCallable, module.generate_thesis_document)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError("论文生成服务未就绪") from exc


def json_outline_to_markdown(outline: list[OutlineChapter]) -> str:
    """将结构化大纲转换为正文生成服务需要的 Markdown。"""

    lines: list[str] = []
    for chapter in outline:
        lines.append(f"## {chapter.chapter}")
        for section in chapter.sections:
            lines.append(f"### {section.name}")
            if section.abstract:
                lines.append(section.abstract.strip())
        lines.append("")
    return "\n".join(lines).strip()


async def generate_outline_for_request(req: OutlineRequest) -> OutlineResponse:
    """根据 API 请求生成论文大纲。"""

    try:
        generate_outline = load_generate_outline()
        outline_data = await generate_outline(
            req.title,
            req.target_word_count,
            req.codetype,
            req.language,
            req.three_level,
            req.aboutmsg,
        )
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"大纲生成失败: {exc}") from exc
    return OutlineResponse(title=req.title, **outline_data)


async def submit_generate_request(
    user: User,
    req: GenerateRequest,
    idempotency_key: str | None = None,
) -> GenerateSubmitResponse:
    """提交接口直连论文生成任务，扣减积分后进入独立 worker 队列。"""

    task_id = create_task_id()
    generation_task, should_start = await PaperOrderService.create_direct_generate_task(
        user,
        task_id=task_id,
        title=req.title,
        request_payload=req.model_dump(mode="json"),
        idempotency_key=idempotency_key,
    )
    if (
        await status_store.read_status_async(generation_task.task_id) is None
        and generation_task.status in {"paid", "generating"}
    ):
        await publish_progress(generation_task.task_id, "queued", "论文生成任务已进入队列")
    if should_start:
        await enqueue_generation_task(generation_task.id)
    return GenerateSubmitResponse(task_id=generation_task.task_id)


async def run_generation_task(generation_task_id: int) -> None:
    """后台执行统一论文生成任务。"""

    generation_task = await PaperOrderService.mark_generation_task_generating_if_paid(generation_task_id)
    if generation_task is None:
        return

    await publish_progress(generation_task.task_id, "started", "论文生成任务已开始")
    with use_runtime_context(
        user_id=generation_task.user_id,
        order_id=generation_task.order_id,
        generation_task_id=generation_task.id,
        task_id=generation_task.task_id,
    ):
        try:
            await _run_order_generation_task(generation_task)
        except Exception as exc:  # noqa: BLE001
            await _mark_generation_failed(generation_task.task_id, exc, generation_task.id)


async def _run_order_generation_task(generation_task: PaperGenerationTask) -> None:
    """执行论文订单生成任务。"""

    from models.paper import PaperOrder

    order = await PaperOrder.filter(id=generation_task.order_id).first()
    if order is None:
        raise RuntimeError("论文订单不存在")
    normalized = PaperOrderService.normalize_generate_input(order)
    if not normalized.outline_json:
        raise RuntimeError("大纲不能为空")

    order.status = "generating"
    order.task_id = generation_task.task_id
    order.started_at = generation_task.started_at
    order.last_error = ""
    await order.save(update_fields=["status", "task_id", "started_at", "last_error", "updated_at"])

    await run_generate_task(
        generation_task.task_id,
        normalized.title,
        json_outline_to_markdown(normalized.outline_json),
        {
            "target_word_count": normalized.target_word_count,
            "author": normalized.author,
            "advisor": normalized.advisor,
            "degree_type": normalized.degree_type,
            "major": normalized.major,
            "school": normalized.school,
            "year_month": normalized.year_month,
            "student_id": normalized.student_id,
            "student_class": normalized.student_class,
        },
        normalized.codetype,
        normalized.wxquote,
        normalized.language,
        normalized.wxnum,
        generation_task_id=generation_task.id,
        callback_url=order.callback_url or "",
        callback_secret=order.callback_secret or "",
        enable_callback=bool(order.callback_url),
    )


def get_task_status(task_id: str) -> TaskStatusResponse:
    """查询生成任务状态，不存在时抛出 404。"""

    data = status_store.read_status(task_id)
    if data is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return TaskStatusResponse(**data)


async def get_task_status_for_user(user: User, task_id: str) -> TaskStatusResponse:
    """查询当前用户可访问的接口直连任务状态。"""

    generation_task = await _get_visible_generation_task(user, task_id)
    if generation_task is not None and generation_task.status in {"paid", "generating"}:
        return _generation_task_status_response(generation_task)
    data = await status_store.read_status_async(task_id)
    if data is not None:
        return TaskStatusResponse(**data)
    if generation_task is not None:
        return _generation_task_status_response(generation_task)
    raise HTTPException(status_code=404, detail="任务不存在")


def get_download_path(task_id: str) -> Path:
    """返回已完成任务的本地 Word 文件路径。"""

    return _download_path_from_status(status_store.read_status(task_id))


def _download_path_from_status(data: dict[str, Any] | None) -> Path:
    """从任务状态中解析可下载的本地 Word 文件路径。"""

    if data is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    if data["status"] != "completed":
        raise HTTPException(status_code=409, detail=f"任务状态为 {data['status']}，无法下载")

    docx_path = data.get("docx_path", "")
    if not docx_path:
        raise HTTPException(status_code=404, detail="文档文件不存在")
    path_obj = Path(docx_path)
    if not path_obj.exists():
        raise HTTPException(status_code=404, detail="文档文件不存在")
    return path_obj


async def get_download_path_for_user(user: User, task_id: str) -> Path:
    """返回当前用户可访问的已完成 Word 文件路径。"""

    await _get_visible_generation_task(user, task_id)
    data = await status_store.read_status_async(task_id)
    return _download_path_from_status(data)


async def run_generate_task(
    task_id: str,
    title: str,
    outline: str,
    cover_kwargs: dict[str, Any] | None = None,
    codetype: str = "否",
    wxquote: str = "标注",
    language: str = "否",
    wxnum: int = 25,
    generation_task_id: int | None = None,
    callback_url: str = "",
    callback_secret: str = "",
    enable_callback: bool = True,
) -> None:
    """后台执行论文生成、上传和业务回调，并同步任务状态。"""

    cover_kwargs = cover_kwargs or {}
    try:
        generate_document = load_generate_document()
        result = await generate_document(
            task_id=task_id,
            title=title,
            outline=outline,
            codetype=codetype,
            wxquote=wxquote,
            language=language,
            wxnum=wxnum,
            **cover_kwargs,
        )
        await _mark_generation_completed(
            task_id,
            result,
            generation_task_id,
            callback_url,
            callback_secret,
            enable_callback,
        )
    except Exception as exc:  # noqa: BLE001
        await _mark_generation_failed(task_id, exc, generation_task_id, callback_url, callback_secret, enable_callback)


async def _get_visible_generation_task(user: User, task_id: str) -> PaperGenerationTask | None:
    generation_task = await PaperGenerationTask.filter(task_id=task_id).first()
    if generation_task is None:
        return None
    if generation_task.user_id != user.id and user.role != "admin":
        raise HTTPException(status_code=404, detail="任务不存在")
    return generation_task


def _generation_task_status_response(generation_task: PaperGenerationTask) -> TaskStatusResponse:
    status = "pending"
    if generation_task.status in {"completed", "failed"}:
        status = generation_task.status
    return TaskStatusResponse(
        task_id=generation_task.task_id,
        status=cast(Any, status),
        message=generation_task.last_error or ("论文生成完成" if generation_task.status == "completed" else "正在生成论文..."),
        stage=generation_task.current_stage or "",
        progress=generation_task.progress,
        events=cast(list[dict[str, Any]], generation_task.process_events or []),
        file_key=generation_task.file_key or "",
        storage_provider=generation_task.storage_provider or "",
        local_file_key=generation_task.local_file_key or "",
        local_download_url=_build_local_download_url(generation_task.local_file_key),
    )


async def _mark_generation_completed(
    task_id: str,
    result: Any,
    generation_task_id: int | None = None,
    callback_url: str = "",
    callback_secret: str = "",
    enable_callback: bool = True,
) -> None:
    from services.thesis.business.order_callback import notify_callback
    from services.thesis.storage.document_storage import store_document

    docx_path = str(_result_value(result, "docx_path", ""))
    await publish_progress(task_id, "storage", "正在保存论文文件")
    stored = await store_document(docx_path, task_id)
    await publish_progress(
        task_id,
        "completed",
        "论文生成完成",
        status="completed",
        storage_provider=stored.storage_provider,
        file_key=stored.file_key,
        download_url=stored.download_url,
        local_file_key=stored.local_file_key,
        local_download_url=stored.local_download_url,
        docx_path=docx_path,
        figure_count=_result_value(result, "figure_count", 0),
        mermaid_count=_result_value(result, "mermaid_count", 0),
        chart_count=_result_value(result, "chart_count", 0),
        ai_image_count=_result_value(result, "ai_image_count", 0),
        fallback_count=_result_value(result, "fallback_count", 0),
        fulltext_char_count=_result_value(result, "fulltext_char_count", 0),
        truncation_warning=_result_value(result, "truncation_warning", False),
    )
    if generation_task_id is not None:
        status_data = await status_store.read_status_async(task_id)
        await PaperOrderService.mark_generation_task_from_status(generation_task_id, status_data)
    if not enable_callback:
        return
    await notify_callback(
        task_id,
        file_key=stored.file_key,
        status="completed",
        error_msg="",
        callback_url=callback_url,
        callback_secret=callback_secret,
        download_url=stored.download_url,
        storage_provider=stored.storage_provider,
        local_file_key=stored.local_file_key,
        local_download_url=stored.local_download_url,
    )


async def _mark_generation_failed(
    task_id: str,
    exc: Exception,
    generation_task_id: int | None = None,
    callback_url: str = "",
    callback_secret: str = "",
    enable_callback: bool = True,
) -> None:
    logger.exception("论文生成失败")
    if is_provider_quota_error(exc):
        error_type = "provider_quota"
        error_msg = "生成服务暂时不可用，本次扣除积分已退回，请稍后重试或联系管理员"
    elif is_provider_config_error(exc):
        error_type = "provider_config"
        error_msg = "生成服务配置异常，本次扣除积分已退回，请联系管理员处理"
    else:
        error_type = "generation_error"
        error_msg = "生成失败，请稍后重试或联系管理员"
    await publish_progress(
        task_id,
        "failed",
        error_msg,
        status="failed",
        error_type=error_type,
        internal_error=str(exc)[:500],
    )
    if generation_task_id is not None:
        status_data = await status_store.read_status_async(task_id)
        await PaperOrderService.mark_generation_task_from_status(generation_task_id, status_data)
    if not enable_callback:
        return
    try:
        from services.thesis.business.order_callback import notify_callback

        await notify_callback(
            task_id,
            file_key="",
            status="failed",
            error_msg=error_msg,
            callback_url=callback_url,
            callback_secret=callback_secret,
        )
    except Exception:  # noqa: BLE001
        logger.exception("失败回调业务系统失败")


def _result_value(result: Any, key: str, default: Any) -> Any:
    if isinstance(result, dict):
        return result.get(key, default)
    return getattr(result, key, default)


def _build_local_download_url(local_file_key: str | None) -> str:
    if not local_file_key:
        return ""
    from services.thesis.storage.document_storage import build_local_download_url

    return build_local_download_url(local_file_key)
