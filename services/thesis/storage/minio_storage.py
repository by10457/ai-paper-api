"""论文文档 MinIO 存储实现。"""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from pathlib import Path

from minio import Minio

from core.config import get_settings
from services.thesis.storage.local_storage import StoredDocument, quote_storage_key

logger = logging.getLogger(__name__)

DOCX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


async def store_to_minio(path: Path, object_key: str, local_result: StoredDocument) -> StoredDocument:
    """上传到 MinIO。"""

    settings = get_settings()
    if not settings.MINIO_ENDPOINT or not settings.MINIO_ACCESS_KEY or not settings.MINIO_SECRET_KEY or not settings.MINIO_BUCKET:
        raise RuntimeError("MinIO 配置不完整")

    client = _create_minio_client()
    exists = await asyncio.to_thread(client.bucket_exists, settings.MINIO_BUCKET)
    if not exists:
        await asyncio.to_thread(client.make_bucket, settings.MINIO_BUCKET)
    await asyncio.to_thread(
        client.fput_object,
        settings.MINIO_BUCKET,
        object_key,
        str(path),
        content_type=DOCX_CONTENT_TYPE,
    )
    logger.info("MinIO 上传成功: file_key=%s", object_key)
    return StoredDocument(
        storage_provider="minio",
        file_key=object_key,
        download_url=build_minio_download_url(object_key),
        local_file_key=local_result.local_file_key,
        local_download_url=local_result.local_download_url,
    )


def build_minio_download_url(file_key: str) -> str:
    """生成 MinIO 下载链接。"""

    settings = get_settings()
    if settings.MINIO_DOMAIN:
        return f"{settings.MINIO_DOMAIN.rstrip('/')}/{quote_storage_key(file_key)}"
    return str(
        _create_minio_client().presigned_get_object(
            settings.MINIO_BUCKET,
            file_key,
            expires=timedelta(seconds=settings.STORAGE_DOWNLOAD_EXPIRES),
        )
    )


def _create_minio_client() -> Minio:
    """创建 MinIO 客户端。"""

    settings = get_settings()
    return Minio(
        settings.MINIO_ENDPOINT.replace("http://", "").replace("https://", ""),
        access_key=settings.MINIO_ACCESS_KEY,
        secret_key=settings.MINIO_SECRET_KEY,
        secure=settings.MINIO_SECURE,
    )
