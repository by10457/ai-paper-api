import asyncio
import logging

import httpx

from core.config import get_settings

logger = logging.getLogger(__name__)

CALLBACK_MAX_ATTEMPTS = 3
CALLBACK_TIMEOUT_SECONDS = 5.0


async def notify_callback(task_id: str, file_key: str, status: str, error_msg: str = "") -> None:
    """通知业务系统论文生成结果。"""

    settings = get_settings()
    if not settings.paper_callback_url:
        logger.info("PAPER_CALLBACK_URL 未配置，跳过回调")
        return

    payload: dict[str, str] = {
        "task_id": task_id,
        "file_key": file_key,
        "status": status,
        "error_msg": error_msg,
        "secret": settings.paper_callback_secret,
    }

    for attempt in range(1, CALLBACK_MAX_ATTEMPTS + 1):
        try:
            async with httpx.AsyncClient(timeout=CALLBACK_TIMEOUT_SECONDS) as client:
                response = await client.post(settings.paper_callback_url, json=payload)
                response.raise_for_status()
                logger.info("回调业务系统成功: task_id=%s, status=%s", task_id, status)
                return
        except Exception as exc:  # noqa: BLE001
            if attempt >= CALLBACK_MAX_ATTEMPTS:
                logger.warning(
                    "回调业务系统最终失败: task_id=%s, status=%s, attempts=%d, err=%s",
                    task_id,
                    status,
                    CALLBACK_MAX_ATTEMPTS,
                    exc,
                )
                return
            delay = 2 ** (attempt - 1)
            logger.debug(
                "回调业务系统失败，稍后重试: task_id=%s, status=%s, attempt=%d/%d, err=%s",
                task_id,
                status,
                attempt,
                CALLBACK_MAX_ATTEMPTS,
                exc,
            )
            await asyncio.sleep(delay)
