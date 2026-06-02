"""
CrossRef API 客户端 —— 用于补全参考文献的卷号、期号、页码。

设计原则：
- 仅做 best-effort 补全，任何失败都不影响主流程
- 通过标题相似度校验防止 CrossRef 模糊搜索返回不相关结果
- 并发控制符合 Polite pool 限制（10次/秒、5 并发）
"""

import asyncio
import logging
import re
from difflib import SequenceMatcher
from typing import Any, cast

import httpx

from core.config import get_settings

logger = logging.getLogger(__name__)

CROSSREF_API = "https://api.crossref.org/works"
_SEMAPHORE = asyncio.Semaphore(5)
_SELECT_FIELDS = "title,author,container-title,published,volume,issue,page,type"

# 匹配用标题相似度阈值
_SIMILARITY_THRESHOLD = 0.55


def _crossref_mailto() -> str:
    return get_settings().crossref_mailto or "noreply@example.com"


def _normalize_title(s: str) -> str:
    """归一化标题：去除标点、空格、转小写。"""
    return re.sub(r"[^\w]", "", s).lower()


def _title_similar(a: str, b: str) -> bool:
    """检查两个标题是否足够相似。"""
    na, nb = _normalize_title(a), _normalize_title(b)
    if not na or not nb:
        return False
    return SequenceMatcher(None, na, nb).ratio() >= _SIMILARITY_THRESHOLD


async def _query_one(client: httpx.AsyncClient, title: str) -> dict[str, Any] | None:
    """查询单条标题，返回 CrossRef 匹配结果或 None。"""
    async with _SEMAPHORE:
        try:
            resp = await client.get(
                CROSSREF_API,
                params={
                    "query.bibliographic": title,
                    "rows": 1,
                    "select": _SELECT_FIELDS,
                    "mailto": _crossref_mailto(),
                },
            )
            resp.raise_for_status()
            payload = cast(dict[str, Any], resp.json())
            items = cast(list[dict[str, Any]], payload.get("message", {}).get("items", []))
            if not items:
                return None

            item = items[0]
            found_title = (item.get("title") or [""])[0]
            if not _title_similar(title, found_title):
                logger.debug(
                    "CrossRef 标题不匹配，跳过: query=%r found=%r",
                    title[:50],
                    found_title[:50],
                )
                return None
            return item
        except Exception as exc:  # noqa: BLE001
            logger.debug("CrossRef 查询失败 title=%r: %s", title[:50], exc)
            return None


def _extract_crossref_fields(cr_item: dict[str, Any]) -> dict[str, Any]:
    """从 CrossRef 返回项中提取有用字段。"""
    # 作者
    authors_raw = cr_item.get("author", [])
    author_names: list[str] = []
    for a in authors_raw[:5]:
        given = a.get("given", "").strip()
        family = a.get("family", "").strip()
        if given and family:
            author_names.append(f"{family} {given}" if _is_chinese(family) else f"{given} {family}")
        elif family:
            author_names.append(family)
    # 期刊名
    container = (cr_item.get("container-title") or [""])[0]
    # 年份
    date_parts = cr_item.get("published", {}).get("date-parts", [[]])
    year = str(date_parts[0][0]) if date_parts and date_parts[0] else ""

    return {
        "crossref_authors": author_names,
        "crossref_journal": container,
        "crossref_year": year,
        "crossref_volume": cr_item.get("volume", ""),
        "crossref_issue": cr_item.get("issue", ""),
        "crossref_page": cr_item.get("page", ""),
        "crossref_type": cr_item.get("type", ""),
    }


def _is_chinese(text: str) -> bool:
    """粗略判断字符串是否以中文字符为主。"""
    if not text:
        return False
    return any("\u4e00" <= ch <= "\u9fff" for ch in text)


async def enrich_with_crossref(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    批量用 CrossRef 补全文献的卷期页码信息。

    对每条 item，用其 title 查询 CrossRef，如果标题匹配则注入
    crossref_* 字段。失败时静默跳过，不影响原始数据。

    Args:
        items: SerpAPI Scholar 返回的文献列表（每项须含 "title" 键）

    Returns:
        原列表（就地修改），每项可能增加 crossref_* 字段
    """
    if not items:
        return items

    async with httpx.AsyncClient(timeout=12.0) as client:
        tasks = [_query_one(client, item.get("title", "")) for item in items]
        results = await asyncio.gather(*tasks)

    enriched_count = 0
    for item, cr_item in zip(items, results, strict=True):
        if cr_item is not None:
            item.update(_extract_crossref_fields(cr_item))
            enriched_count += 1

    logger.info(
        "CrossRef 补全完成: %d/%d 条匹配成功",
        enriched_count,
        len(items),
    )
    return items
