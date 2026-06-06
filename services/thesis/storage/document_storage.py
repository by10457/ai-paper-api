"""论文文档存储统一入口。"""

from __future__ import annotations

import logging
from pathlib import Path

from core.config import get_settings
from services.thesis.storage.local_storage import (
    StoredDocument,
    build_local_download_url,
    store_to_local,
)

logger = logging.getLogger(__name__)


async def store_document(local_path: str, task_id: str) -> StoredDocument:
    """保存论文文档并按配置上传到远端存储，远端失败时降级到本地文件。"""

    path = _validate_local_path(local_path)
    local_result = store_to_local(path)

    settings = get_settings()
    provider = settings.STORAGE_PROVIDER.strip().lower() or "local"
    if provider == "local":
        return local_result

    object_key = build_remote_object_key(path, task_id)
    try:
        if provider == "qiniu":
            from services.thesis.storage.qiniu_storage import store_to_qiniu

            return await store_to_qiniu(path, object_key, local_result)
        if provider == "minio":
            from services.thesis.storage.minio_storage import store_to_minio

            return await store_to_minio(path, object_key, local_result)
        if provider == "cos":
            from services.thesis.storage.cos_storage import store_to_cos

            return await store_to_cos(path, object_key, local_result)
        logger.warning("未知存储类型 %s，使用本地文件兜底", provider)
    except Exception as exc:  # noqa: BLE001
        logger.warning("远端存储失败，使用本地文件兜底: provider=%s, err=%s", provider, exc)
    return local_result


def build_download_url(
    storage_provider: str | None,
    file_key: str | None,
    local_file_key: str | None = None,
) -> str | None:
    """根据存储类型和 key 生成下载地址。"""

    provider = (storage_provider or "").strip().lower()
    key = (file_key or "").strip()
    if key.startswith(("http://", "https://")):
        return key
    if provider == "qiniu" and key:
        from services.thesis.storage.qiniu_storage import build_qiniu_private_download_url

        return build_qiniu_private_download_url(key)
    if provider == "minio" and key:
        from services.thesis.storage.minio_storage import build_minio_download_url

        return build_minio_download_url(key)
    if provider == "cos" and key:
        from services.thesis.storage.cos_storage import build_cos_download_url

        return build_cos_download_url(key)
    if local_file_key:
        return build_local_download_url(local_file_key)
    if provider == "local" and key:
        return build_local_download_url(key)
    return None


def build_remote_object_key(local_path: Path, task_id: str) -> str:
    """生成远端对象 key。"""

    settings = get_settings()
    prefix = settings.STORAGE_OBJECT_PREFIX.strip().strip("/") or "paper"
    return f"{prefix}/{task_id}/{local_path.name}"


def _validate_local_path(local_path: str) -> Path:
    """校验本地文档路径。"""

    if not local_path:
        raise RuntimeError("待存储文档路径为空")
    path = Path(local_path)
    if not path.exists():
        raise RuntimeError(f"待存储文档不存在: {local_path}")
    return path
