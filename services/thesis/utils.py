import re
import unicodedata


def sanitize_filename(name: str, max_length: int = 80) -> str:
    """将用户输入标题转换为安全文件名。"""

    normalized = unicodedata.normalize("NFC", name)
    no_control = re.sub(r"[\x00-\x1f\x7f]", "", normalized)
    no_path = no_control.replace("/", "_").replace("\\", "_").replace("..", "_")
    no_reserved = re.sub(r'[<>:"|?*]', "_", no_path)
    cleaned = no_reserved.strip().strip(".")
    truncated = cleaned[:max_length]
    return truncated or "untitled"
