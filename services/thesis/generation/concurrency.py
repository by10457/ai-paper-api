"""论文生成外部依赖并发保护。"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from core.config import get_settings

_SEMAPHORES: dict[tuple[str, int], asyncio.Semaphore] = {}


def _semaphore(name: str, limit: int) -> asyncio.Semaphore:
    """按名称和限制值复用进程内信号量。"""

    key = (name, limit)
    semaphore = _SEMAPHORES.get(key)
    if semaphore is None:
        semaphore = asyncio.Semaphore(limit)
        _SEMAPHORES[key] = semaphore
    return semaphore


@asynccontextmanager
async def text_long_slot() -> AsyncIterator[None]:
    """长文本 LLM 调用并发槽，主要用于论文正文生成。"""

    async with _semaphore("text_long", get_settings().TEXT_LONG_CONCURRENCY):
        yield


@asynccontextmanager
async def text_short_slot() -> AsyncIterator[None]:
    """短文本 LLM 调用并发槽，用于大纲、摘要、致谢和参考文献筛选等。"""

    async with _semaphore("text_short", get_settings().TEXT_SHORT_CONCURRENCY):
        yield


@asynccontextmanager
async def image_model_slot() -> AsyncIterator[None]:
    """图片模型调用并发槽。"""

    async with _semaphore("image_model", get_settings().IMAGE_MODEL_CONCURRENCY):
        yield


@asynccontextmanager
async def serpapi_slot() -> AsyncIterator[None]:
    """SerpAPI 检索调用并发槽。"""

    async with _semaphore("serpapi", get_settings().SERPAPI_CONCURRENCY):
        yield


@asynccontextmanager
async def crossref_slot() -> AsyncIterator[None]:
    """CrossRef 补全调用并发槽。"""

    async with _semaphore("crossref", get_settings().CROSSREF_CONCURRENCY):
        yield
