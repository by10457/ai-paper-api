import asyncio
import logging

import httpx

from core.config import get_settings

logger = logging.getLogger(__name__)


async def notify_callback(task_id: str, file_key: str, status: str, error_msg: str = "") -> None:
    """通知业务系统论文生成结果。"""

    settings = get_settings()
    if not settings.paper_callback_url:
        logger.warning("PAPER_CALLBACK_URL 未配置，跳过回调")
        return

    payload: dict[str, str] = {
        "task_id": task_id,
        "file_key": file_key,
        "status": status,
        "error_msg": error_msg,
        "secret": settings.paper_callback_secret,
    }

    for attempt in range(3):
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(settings.paper_callback_url, json=payload)
                response.raise_for_status()
                logger.info("回调业务系统成功: task_id=%s, status=%s", task_id, status)
                return
        except Exception as exc:  # noqa: BLE001
            delay = 2 ** attempt
            logger.warning(
                "回调业务系统失败: task_id=%s, status=%s, attempt=%d/3, err=%s",
                task_id,
                status,
                attempt + 1,
                exc,
            )
            await asyncio.sleep(delay)

    logger.error("回调业务系统最终失败: task_id=%s, status=%s", task_id, status)
