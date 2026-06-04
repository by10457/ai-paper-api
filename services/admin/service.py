"""管理端服务聚合入口。"""

from services.admin.logs import AdminLogService
from services.admin.model_configs import AdminModelConfigService
from services.admin.orders import AdminOrderService
from services.admin.overview import AdminOverviewService
from services.admin.users import AdminUserService


class AdminService(
    AdminOverviewService,
    AdminUserService,
    AdminOrderService,
    AdminModelConfigService,
    AdminLogService,
):
    """兼容原有 AdminService 调用方式，具体业务按模块拆分实现。"""
