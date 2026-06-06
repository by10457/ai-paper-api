"""论文文档七牛云存储实现。"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import qiniu

from core.config import get_settings
from services.thesis.storage.local_storage import StoredDocument, quote_storage_key

logger = logging.getLogger(__name__)

MAX_UPLOAD_RETRIES = 2


async def store_to_qiniu(path: Path, object_key: str, local_result: StoredDocument) -> StoredDocument:
    """上传到七牛云。"""

    settings = get_settings()
    if not settings.qiniu_access_key or not settings.qiniu_secret_key or not settings.qiniu_bucket:
        raise RuntimeError("七牛云配置不完整")

    auth = qiniu.Auth(settings.qiniu_access_key, settings.qiniu_secret_key)
    last_error: Exception | None = None
    for attempt in range(1, MAX_UPLOAD_RETRIES + 2):
        try:
            token = auth.upload_token(settings.qiniu_bucket, object_key)
            ret, info = await asyncio.to_thread(qiniu.put_file, token, object_key, str(path))
            if info.status_code == 200 and ret:
                logger.info("七牛上传成功: file_key=%s, attempt=%d", object_key, attempt)
                return StoredDocument(
                    storage_provider="qiniu",
                    file_key=object_key,
                    download_url=build_qiniu_private_download_url(object_key),
                    local_file_key=local_result.local_file_key,
                    local_download_url=local_result.local_download_url,
                )
            raise RuntimeError(f"七牛返回非 200: {info}")
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            logger.warning("七牛上传失败: file_key=%s, attempt=%d/%d, err=%s", object_key, attempt, MAX_UPLOAD_RETRIES + 1, exc)
    raise RuntimeError(f"七牛上传最终失败: {last_error}") from last_error


def build_qiniu_private_download_url(file_key: str) -> str:
    """根据七牛文件 key 生成私有空间临时下载链接。"""

    settings = get_settings()
    if not settings.qiniu_access_key or not settings.qiniu_secret_key or not settings.qiniu_domain:
        raise RuntimeError("七牛云下载配置不完整")

    public_url = f"{settings.qiniu_domain.rstrip('/')}/{quote_storage_key(file_key)}"
    auth = qiniu.Auth(settings.qiniu_access_key, settings.qiniu_secret_key)
    return str(auth.private_download_url(public_url, expires=settings.qiniu_download_expires))


async def upload_to_qiniu(local_path: str, task_id: str) -> str:
    """上传 docx 到当前存储配置，返回七牛兼容 file_key。"""

    from services.thesis.storage.document_storage import store_document

    stored = await store_document(local_path, task_id)
    return stored.file_key
