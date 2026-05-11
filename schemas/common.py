"""
统一 API 响应格式

约定所有接口返回：
{
    "code": 200,
    "message": "ok",
    "data": ...
}
"""

from typing import Any, Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class Response(BaseModel, Generic[T]):
    code: int = 200
    message: str = "ok"
    data: T | None = None

    @classmethod
    def ok(cls, data: Any = None, message: str = "ok") -> "Response":
        return cls(code=200, message=message, data=data)

    @classmethod
    def error(cls, code: int = 400, message: str = "error") -> "Response":
        return cls(code=code, message=message, data=None)


class PageResponse(BaseModel, Generic[T]):
    """分页响应"""

    total: int
    page: int
    page_size: int
    items: list[T]
