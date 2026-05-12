"""论文大纲与正文生成任务编排。"""

import logging
import uuid
from collections.abc import Awaitable, Callable
from importlib import import_module
from pathlib import Path
from typing import Any, cast

from fastapi import BackgroundTasks, HTTPException

from schemas.thesis import (
    GenerateRequest,
    GenerateSubmitResponse,
    OutlineChapter,
    OutlineRequest,
    OutlineResponse,
    TaskStatusResponse,
)
from services.thesis import status_store

logger = logging.getLogger(__name__)

GenerateOutlineCallable = Callable[..., Awaitable[dict[str, Any]]]
GenerateDocumentCallable = Callable[..., Awaitable[Any]]


def create_task_id() -> str:
    """创建对外暴露的短任务 ID。"""

    return uuid.uuid4().hex[:12]


def load_generate_outline() -> GenerateOutlineCallable:
    """延迟加载大纲服务，避免应用启动阶段过早初始化 LLM 链。"""

    try:
        module = import_module("services.thesis.outline_service")
        return cast(GenerateOutlineCallable, module.generate_outline)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError("论文大纲服务未就绪") from exc


def load_generate_document() -> GenerateDocumentCallable:
    """延迟加载正文生成服务，降低测试和路由导入成本。"""

    try:
        module = import_module("services.thesis")
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


def submit_generate_request(req: GenerateRequest, background_tasks: BackgroundTasks) -> GenerateSubmitResponse:
    """提交免费论文生成任务并写入初始状态。"""

    task_id = create_task_id()
    status_store.write_status(task_id, "pending", message="正在生成论文...")
    background_tasks.add_task(
        run_generate_task,
        task_id,
        req.title,
        json_outline_to_markdown(req.outline_json),
        _cover_kwargs(req),
        req.codetype,
        req.wxquote,
        req.language,
        req.wxnum,
    )
    return GenerateSubmitResponse(task_id=task_id)


def get_task_status(task_id: str) -> TaskStatusResponse:
    """查询生成任务状态，不存在时抛出 404。"""

    data = status_store.read_status(task_id)
    if data is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return TaskStatusResponse(**data)


def get_download_path(task_id: str) -> Path:
    """返回已完成任务的本地 Word 文件路径。"""

    data = status_store.read_status(task_id)
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


async def run_generate_task(
    task_id: str,
    title: str,
    outline: str,
    cover_kwargs: dict[str, Any] | None = None,
    codetype: str = "否",
    wxquote: str = "标注",
    language: str = "否",
    wxnum: int = 25,
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
        await _mark_generation_completed(task_id, result)
    except Exception as exc:  # noqa: BLE001
        await _mark_generation_failed(task_id, exc)


def _cover_kwargs(req: GenerateRequest) -> dict[str, Any]:
    return {
        "target_word_count": req.target_word_count,
        "author": req.author,
        "advisor": req.advisor,
        "degree_type": req.degree_type,
        "major": req.major,
        "school": req.school,
        "year_month": req.year_month,
        "student_id": req.student_id,
        "student_class": req.student_class,
    }


async def _mark_generation_completed(task_id: str, result: Any) -> None:
    from services.storage.callback import notify_callback
    from services.storage.qiniu_uploader import upload_to_qiniu

    docx_path = str(_result_value(result, "docx_path", ""))
    file_key = await upload_to_qiniu(docx_path, task_id)
    await notify_callback(task_id, file_key, status="completed")
    status_store.write_status(
        task_id,
        "completed",
        message="论文生成完成",
        file_key=file_key,
        docx_path=docx_path,
        figure_count=_result_value(result, "figure_count", 0),
        mermaid_count=_result_value(result, "mermaid_count", 0),
        chart_count=_result_value(result, "chart_count", 0),
        ai_image_count=_result_value(result, "ai_image_count", 0),
        fallback_count=_result_value(result, "fallback_count", 0),
        fulltext_char_count=_result_value(result, "fulltext_char_count", 0),
        truncation_warning=_result_value(result, "truncation_warning", False),
    )


async def _mark_generation_failed(task_id: str, exc: Exception) -> None:
    logger.exception("论文生成失败")
    error_msg = str(exc)[:500]
    status_store.write_status(task_id, "failed", message=f"生成失败: {error_msg}")
    try:
        from services.storage.callback import notify_callback

        await notify_callback(task_id, file_key="", status="failed", error_msg=error_msg)
    except Exception:  # noqa: BLE001
        logger.exception("失败回调业务系统失败")


def _result_value(result: Any, key: str, default: Any) -> Any:
    if isinstance(result, dict):
        return result.get(key, default)
    return getattr(result, key, default)
