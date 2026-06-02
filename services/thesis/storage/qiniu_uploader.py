import asyncio
import logging
from pathlib import Path

import qiniu

from core.config import get_settings

logger = logging.getLogger(__name__)

MAX_UPLOAD_RETRIES = 2


async def upload_to_qiniu(local_path: str, task_id: str) -> str:
    """上传 docx 到七牛云，返回 file_key。"""

    if not local_path:
        raise RuntimeError("待上传文档路径为空")

    settings = get_settings()
    if not settings.qiniu_access_key or not settings.qiniu_secret_key or not settings.qiniu_bucket:
        raise RuntimeError("七牛云配置不完整")

    auth = qiniu.Auth(settings.qiniu_access_key, settings.qiniu_secret_key)
    file_key = f"paper/{task_id}/{Path(local_path).name}"
    last_error: Exception | None = None

    for attempt in range(1, MAX_UPLOAD_RETRIES + 2):
        try:
            token = auth.upload_token(settings.qiniu_bucket, file_key)
            ret, info = await asyncio.to_thread(qiniu.put_file, token, file_key, local_path)
            if info.status_code == 200 and ret:
                logger.info("七牛上传成功: file_key=%s, attempt=%d", file_key, attempt)
                return file_key
            raise RuntimeError(f"七牛返回非 200: {info}")
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            logger.warning(
                "七牛上传失败: file_key=%s, attempt=%d/%d, err=%s",
                file_key,
                attempt,
                MAX_UPLOAD_RETRIES + 1,
                exc,
            )

    raise RuntimeError(f"七牛上传最终失败: {last_error}") from last_error
