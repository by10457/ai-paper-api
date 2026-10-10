"""论文文档通用工具函数。"""

import re
import unicodedata

# 对外下载文件使用中文文档类型，与内部业务标识分离。
DOCUMENT_TYPE_NAMES = {
    "thesis": "论文",
    "proposal_report": "开题报告",
    "literature_review": "文献综述",
    "task_book": "任务书",
}

def sanitize_filename(name: str, max_length: int = 80) -> str:
    """将用户输入标题转换为安全文件名。"""

    normalized = unicodedata.normalize("NFC", name)
    no_control = re.sub(r"[\x00-\x1f\x7f]", "", normalized)
    no_path = no_control.replace("/", "_").replace("\\", "_").replace("..", "_")
    no_reserved = re.sub(r'[<>:"|?*]', "_", no_path)
    cleaned = no_reserved.strip().strip(".")
    truncated = cleaned[:max_length]
    return truncated or "untitled"


# 四类文档使用同一命名规则，任务 ID 保证重复下载稳定且不同任务不冲突。
def build_document_filename(title: str, document_type: str, task_id: str) -> str:
    """生成安全的中文 DOCX 文件名。

    Args:
        title: 用户确认的文档标题。
        document_type: 内部文档类型。
        task_id: 服务端生成任务的唯一 ID。

    Returns:
        标题-中文文档类型-任务ID.docx。
    """
    suffix = f"-{DOCUMENT_TYPE_NAMES[document_type]}-{sanitize_filename(task_id)}.docx"
    # Linux 常见文件系统限制单个文件名为 255 字节，中文标题需按 UTF-8 计量。
    title_budget = 255 - len(suffix.encode("utf-8"))
    safe_title = sanitize_filename(title).encode("utf-8")[:title_budget].decode("utf-8", errors="ignore")
    return f"{safe_title}{suffix}"
