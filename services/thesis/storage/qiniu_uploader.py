import asyncio
import logging
from pathlib import Path
from urllib.parse import quote

import qiniu

from core.config import get_settings

logger = logging.getLogger(__name__)

MAX_UPLOAD_RETRIES = 2


def build_qiniu_private_download_url(file_key: str) -> str:
    """根据七牛文件 key 生成私有空间临时下载链接。"""

    settings = get_settings()
    if not settings.qiniu_access_key or not settings.qiniu_secret_key or not settings.qiniu_domain:
        raise RuntimeError("七牛云下载配置不完整")

    normalized_key = file_key.strip().lstrip("/")
    if not normalized_key:
        raise RuntimeError("七牛云文件 key 为空")

    encoded_key = "/".join(quote(part, safe="") for part in normalized_key.split("/"))
    public_url = f"{settings.qiniu_domain.rstrip('/')}/{encoded_key}"
    auth = qiniu.Auth(settings.qiniu_access_key, settings.qiniu_secret_key)
    return str(auth.private_download_url(public_url, expires=settings.qiniu_download_expires))


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
