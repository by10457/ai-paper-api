"""论文生成任务状态的本地文件存储。"""

import json
from pathlib import Path
from typing import Any, cast

from core.config import get_settings

OUTPUT_ROOT = Path(get_settings().thesis_output_root)
STATUS_FILE_NAME = "status.json"


def status_path(task_id: str) -> Path:
    """返回任务状态文件路径。"""

    return OUTPUT_ROOT / task_id / STATUS_FILE_NAME


def write_status(task_id: str, status: str, **extra: Any) -> None:
    """写入任务状态，供异步生成流程和轮询接口共享。"""

    path = status_path(task_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"task_id": task_id, "status": status, **extra}
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def read_status(task_id: str) -> dict[str, Any] | None:
    """读取任务状态，不存在时返回 None。"""

    path = status_path(task_id)
    if not path.exists():
        return None
    return cast("dict[str, Any]", json.loads(path.read_text(encoding="utf-8")))
