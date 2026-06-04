"""用户侧服务包，对外保持原有 services.user 导入入口。"""

from services.user.service import UserService

__all__ = ["UserService"]
