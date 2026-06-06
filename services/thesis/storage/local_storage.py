"""论文文档本地存储实现。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from core.config import get_settings


@dataclass(frozen=True)
class StoredDocument:
    """论文文档存储结果。"""

    storage_provider: str
    file_key: str
    download_url: str
    local_file_key: str
    local_download_url: str


def store_to_local(local_path: Path) -> StoredDocument:
    """记录本地文件存储结果。"""

    local_file_key = build_local_file_key(local_path)
    local_download_url = build_local_download_url(local_file_key)
    return StoredDocument(
        storage_provider="local",
        file_key=local_file_key,
        download_url=local_download_url,
        local_file_key=local_file_key,
        local_download_url=local_download_url,
    )


def build_local_file_key(local_path: Path) -> str:
    """生成 public 目录下的本地文件 key。"""

    public_root = Path("public").resolve()
    resolved_path = local_path.resolve()
    try:
        return resolved_path.relative_to(public_root).as_posix()
    except ValueError:
        return local_path.as_posix()


def build_local_download_url(local_file_key: str) -> str:
    """生成本地静态文件下载 URL。"""

    encoded_key = quote_storage_key(local_file_key.strip().lstrip("/"))
    path = f"/{encoded_key}"
    base_url = get_settings().public_base_url.strip().rstrip("/")
    if base_url:
        return f"{base_url}{path}"
    return path


def quote_storage_key(file_key: str) -> str:
    """按路径段编码对象 key。"""

    normalized_key = file_key.strip().lstrip("/")
    if not normalized_key:
        raise RuntimeError("文件 key 为空")
    return "/".join(quote(part, safe="") for part in normalized_key.split("/"))
