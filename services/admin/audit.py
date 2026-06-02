"""管理端审计日志写入工具。"""

from __future__ import annotations

from typing import Any

from models.admin import AuditLog
from models.user import User


async def write_audit_log(
    *,
    operator: User | None,
    action: str,
    target_type: str,
    summary: str,
    target_id: str | int | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    ip_address: str | None = None,
) -> None:
    """记录管理员关键操作，before/after 用于保留变更快照。"""

    await AuditLog.create(
        operator=operator,
        action=action,
        target_type=target_type,
        target_id=str(target_id) if target_id is not None else None,
        summary=summary,
        before=before,
        after=after,
        ip_address=ip_address,
    )
