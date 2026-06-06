"""论文文档腾讯云 COS 存储实现。"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from qcloud_cos import CosConfig, CosS3Client

from core.config import get_settings
from services.thesis.storage.local_storage import StoredDocument, quote_storage_key

logger = logging.getLogger(__name__)

DOCX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


async def store_to_cos(path: Path, object_key: str, local_result: StoredDocument) -> StoredDocument:
    """上传到腾讯云 COS。"""

    settings = get_settings()
    if not settings.COS_SECRET_ID or not settings.COS_SECRET_KEY or not settings.COS_BUCKET or not settings.COS_REGION:
        raise RuntimeError("腾讯云 COS 配置不完整")
    if not _is_cos_key_allowed(object_key):
        raise RuntimeError(f"COS 对象 key 不在允许前缀内: {object_key}")

    client = _create_cos_client()
    await asyncio.to_thread(
        client.upload_file,
        Bucket=settings.COS_BUCKET,
        Key=object_key,
        LocalFilePath=str(path),
        ContentType=DOCX_CONTENT_TYPE,
    )
    logger.info("腾讯云 COS 上传成功: file_key=%s", object_key)
    return StoredDocument(
        storage_provider="cos",
        file_key=object_key,
        download_url=build_cos_download_url(object_key),
        local_file_key=local_result.local_file_key,
        local_download_url=local_result.local_download_url,
    )


def build_cos_download_url(file_key: str) -> str:
    """生成腾讯云 COS 下载链接。"""

    settings = get_settings()
    if settings.COS_DOMAIN:
        return f"{settings.COS_DOMAIN.rstrip('/')}/{quote_storage_key(file_key)}"
    if settings.COS_ACCESS_POLICY.strip().upper() == "PUBLIC_READ":
        return f"https://{settings.COS_BUCKET}.cos.{settings.COS_REGION}.myqcloud.com/{quote_storage_key(file_key)}"
    return str(
        _create_cos_client().get_presigned_download_url(
            Bucket=settings.COS_BUCKET,
            Key=file_key,
            Expired=settings.STORAGE_DOWNLOAD_EXPIRES,
        )
    )


def _create_cos_client() -> CosS3Client:
    """创建腾讯云 COS 客户端。"""

    settings = get_settings()
    config = CosConfig(
        Region=settings.COS_REGION,
        SecretId=settings.COS_SECRET_ID,
        SecretKey=settings.COS_SECRET_KEY,
        Scheme="https",
    )
    return CosS3Client(config)


def _is_cos_key_allowed(file_key: str) -> bool:
    """检查 COS 上传前缀。"""

    allow_prefix = get_settings().COS_UPLOAD_ALLOW_PREFIX.strip()
    if not allow_prefix or allow_prefix == "*":
        return True
    return file_key.startswith(allow_prefix.strip("/"))
