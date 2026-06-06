"""论文生成完成回调业务服务。"""

import asyncio
import logging

import httpx

from core.config import get_settings

logger = logging.getLogger(__name__)

CALLBACK_MAX_ATTEMPTS = 3
CALLBACK_TIMEOUT_SECONDS = 5.0


async def notify_callback(
    task_id: str,
    file_key: str,
    status: str,
    error_msg: str = "",
    callback_url: str = "",
    callback_secret: str = "",
    download_url: str = "",
    storage_provider: str = "",
    local_file_key: str = "",
    local_download_url: str = "",
) -> None:
    """通知业务系统论文生成结果。"""

    settings = get_settings()
    target_url = callback_url.strip() or settings.paper_callback_url
    secret = callback_secret.strip() or settings.paper_callback_secret
    if not target_url:
        logger.info("回调地址未配置，跳过回调")
        return

    payload: dict[str, str] = {
        "task_id": task_id,
        "file_key": file_key,
        "download_url": download_url,
        "storage_provider": storage_provider,
        "local_file_key": local_file_key,
        "local_download_url": local_download_url,
        "status": status,
        "error_msg": error_msg,
    }
    headers = {"X-Internal-Secret": secret} if secret else None

    for attempt in range(1, CALLBACK_MAX_ATTEMPTS + 1):
        try:
            async with httpx.AsyncClient(timeout=CALLBACK_TIMEOUT_SECONDS) as client:
                response = await client.post(target_url, json=payload, headers=headers)
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
