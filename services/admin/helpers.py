"""管理端通用查询辅助函数。"""

from fastapi import HTTPException, status

from models.admin import ModelConfig
from models.paper import PaperOrder
from models.user import User


async def get_user_or_404(user_id: int) -> User:
    """查询用户，不存在时转换为统一的 404 业务异常。"""

    user = await User.filter(id=user_id).first()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")
    return user


async def get_order_or_404(order_id: int) -> PaperOrder:
    """查询论文订单，并预加载详情页和订单操作需要的关联数据。"""

    order = await PaperOrder.filter(id=order_id).select_related("user", "outline_record").first()
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="订单不存在")
    return order


async def get_model_config_or_404(config_id: int) -> ModelConfig:
    """查询模型配置，不存在时转换为统一的 404 业务异常。"""

    config = await ModelConfig.filter(id=config_id).first()
    if config is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="模型配置不存在")
    return config
