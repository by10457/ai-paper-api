"""论文材料生成任务编排。"""

from __future__ import annotations

import logging

from llm.client import is_provider_config_error, is_provider_quota_error
from models.paper_material import ThesisMaterialGenerationTask, ThesisMaterialOrder
from services.thesis.business.order_callback import notify_callback
from services.thesis.generation import status_store
from services.thesis.generation.progress import publish_progress
from services.thesis.generation.runtime_context import use_runtime_context
from services.thesis.storage.document_storage import store_document
from services.thesis_material.generation import generate_thesis_material_document
from services.thesis_material.order_service import ThesisMaterialOrderService

logger = logging.getLogger(__name__)

_DOCUMENT_LABELS = {
    "proposal_report": "开题报告",
    "literature_review": "文献综述",
    "task_book": "任务书",
}


async def run_thesis_material_generation_task(task_db_id: int) -> None:
    """执行独立的论文材料生成任务。

    Args:
        task_db_id: 数据库 ``paper_material_generation_tasks`` 表的主键。
    """

    task = await ThesisMaterialOrderService.mark_task_generating_if_paid(task_db_id)
    if task is None:
        return
    order = await ThesisMaterialOrder.filter(id=task.order_id).first()
    if order is None:
        await _handle_failure(task, RuntimeError("论文材料订单不存在"), None)
        return

    with use_runtime_context(
        user_id=task.user_id,
        thesis_material_order_id=order.id,
        thesis_material_generation_task_id=task.id,
        task_id=task.task_id,
    ):
        await publish_progress(task.task_id, "started", f"{_label(task)}生成任务已开始", progress=5)
        try:
            await _generate_and_store(task, order)
        except Exception as exc:  # noqa: BLE001
            await _handle_failure(task, exc, order)


async def _generate_and_store(task: ThesisMaterialGenerationTask, order: ThesisMaterialOrder) -> None:
    """生成、存储文档并同步最终状态。"""

    request_payload = order.request_payload if isinstance(order.request_payload, dict) else {}
    result = await generate_thesis_material_document(
        task_id=task.task_id,
        document_type=task.document_type,
        request_payload=request_payload,
    )
    docx_path = str(result.get("docx_path") or "")
    await publish_progress(task.task_id, "uploading", f"正在保存{_label(task)}文件", progress=96)
    stored = await store_document(docx_path, task.task_id)
    await publish_progress(
        task.task_id,
        "completed",
        f"{_label(task)}生成完成",
        progress=100,
        status="completed",
        storage_provider=stored.storage_provider,
        file_key=stored.file_key,
        download_url=stored.download_url,
        local_file_key=stored.local_file_key,
        local_download_url=stored.local_download_url,
        docx_path=docx_path,
        result_data=result.get("result_data"),
        fulltext_char_count=result.get("fulltext_char_count", 0),
    )
    status_data = await status_store.read_status_async(task.task_id) or {}
    await ThesisMaterialOrderService.mark_completed(task.id, status_data)
    if order.callback_url:
        await notify_callback(
            task.task_id,
            file_key=stored.file_key,
            status="completed",
            callback_url=order.callback_url,
            callback_secret=order.callback_secret or "",
            download_url=stored.download_url,
            storage_provider=stored.storage_provider,
            local_file_key=stored.local_file_key,
            local_download_url=stored.local_download_url,
        )


async def _handle_failure(
    task: ThesisMaterialGenerationTask,
    exc: Exception,
    order: ThesisMaterialOrder | None,
) -> None:
    """记录失败、安排重试，最终失败时完成退款和回调。"""

    logger.exception("论文材料生成失败: task_id=%s", task.task_id, exc_info=exc)
    if is_provider_quota_error(exc):
        error_type = "provider_quota"
        message = "生成服务暂时不可用，本次扣除积分已退回，请稍后重试或联系管理员"
    elif is_provider_config_error(exc):
        error_type = "provider_config"
        message = "生成服务配置异常，本次扣除积分已退回，请联系管理员处理"
    else:
        error_type = "generation_error"
        message = "生成失败，请稍后重试或联系管理员"

    final_failure = await ThesisMaterialOrderService.handle_failed_task(task.id, message, error_type)
    await publish_progress(
        task.task_id,
        "failed" if final_failure else "retrying",
        message if final_failure else "生成暂未成功，系统已安排自动重试",
        progress=100 if final_failure else 5,
        status="failed" if final_failure else "pending",
        error_type=error_type,
        internal_error=str(exc)[:500],
    )
    if final_failure and order is not None and order.callback_url:
        await notify_callback(
            task.task_id,
            file_key="",
            status="failed",
            error_msg=message,
            callback_url=order.callback_url,
            callback_secret=order.callback_secret or "",
        )


def _label(task: ThesisMaterialGenerationTask) -> str:
    """返回任务类型的中文名称。"""

    return _DOCUMENT_LABELS.get(task.document_type, "论文材料")


__all__ = ["run_thesis_material_generation_task"]
