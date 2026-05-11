"""
健康检查接口测试

运行：
    uv run pytest tests/ -v
    uv run pytest tests/ -v --asyncio-mode=auto
"""

from collections.abc import Awaitable, Callable, Coroutine
from typing import Any, cast

import pytest
from httpx import ASGITransport, AsyncClient

from app import app

ASGIMessage = dict[str, Any]
ASGIReceive = Callable[[], Awaitable[ASGIMessage]]
ASGISend = Callable[[ASGIMessage], Coroutine[None, None, None]]
ASGIApp = Callable[[ASGIMessage, ASGIReceive, ASGISend], Coroutine[None, None, None]]


@pytest.mark.asyncio
async def test_health() -> None:
    # FastAPI 是合法 ASGI 应用；这里收窄类型以匹配 httpx 0.27 的 ASGITransport 标注。
    async with AsyncClient(transport=ASGITransport(app=cast(ASGIApp, app)), base_url="http://test") as client:
        response = await client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["code"] == 200
