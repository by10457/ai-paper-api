"""管理端服务包，对外保持原有 services.admin 导入入口。"""

from services.admin.audit import write_audit_log
from services.admin.service import AdminService
from services.admin.utils import mask_secret

__all__ = ["AdminService", "mask_secret", "write_audit_log"]
