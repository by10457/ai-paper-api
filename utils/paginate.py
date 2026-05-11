"""
分页工具

使用方式：
    from utils.paginate import paginate
    result = await paginate(User.all(), page=1, page_size=20)
"""

from typing import TypeVar

from tortoise.models import Model
from tortoise.queryset import QuerySet

M = TypeVar("M", bound=Model)


async def paginate(
    queryset: QuerySet,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    """对 Tortoise-ORM QuerySet 进行分页，返回 PageResponse 所需的字典。"""
    page = max(1, page)
    page_size = min(100, max(1, page_size))
    offset = (page - 1) * page_size

    total = await queryset.count()
    items = await queryset.offset(offset).limit(page_size)

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": items,
    }
