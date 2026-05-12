"""
参考文献生成服务。

流程：
1. LLM 提取检索关键词
2. 并发调用 SerpAPI Google Scholar
3. LLM 进行相关性筛选
4. CrossRef 补全卷期页码（best-effort）
5. 使用实际返回字段格式化参考文献
6. 返回已编号字符串
"""

import asyncio
import json
import logging
import re
from typing import Any, cast

import httpx
from langchain_core.language_models import BaseChatModel
from langchain_core.output_parsers import StrOutputParser

from core.config import get_settings
from llm.client import create_llm
from llm.prompts.thesis_reference_prompt import (
    REFERENCE_FILTER_PROMPT,
    REFERENCE_KEYWORD_PROMPT,
)

logger = logging.getLogger(__name__)

SERPAPI_BASE = "https://serpapi.com/search"


async def _search_scholar(query: str, num: int = 8) -> list[dict[str, Any]]:
    """调用 SerpAPI Google Scholar，失败返回空列表。"""
    api_key = get_settings().serpapi_key
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(
                SERPAPI_BASE,
                params={
                    "engine": "google_scholar",
                    "q": query,
                    "num": num,
                    "api_key": api_key,
                },
            )
            response.raise_for_status()
            payload = cast(dict[str, Any], response.json())
            return cast(list[dict[str, Any]], payload.get("organic_results", []))
    except Exception as exc:  # noqa: BLE001
        logger.warning("SerpAPI 搜索失败 query=%r: %s", query, exc)
        return []


def _title_key(item: dict[str, Any]) -> str:
    return str(item.get("title", "")).strip().lower()


YEAR_PATTERN = re.compile(r"(?<!\d)((?:19|20)\d{2})(?!\d)")
UNIVERSITY_RE = re.compile(
    r"(?<![\w])([^,，。；;:\-\s]{1,30}(?:大学|学院|研究院|科学院|University|Institute|College))(?!学报)",
    re.IGNORECASE,
)
JOURNAL_HINT_RE = re.compile(r"学报|期刊|杂志|Journal|Review|Transactions", re.IGNORECASE)
DOMAIN_RE = re.compile(r"^[\w.-]+\.\w{2,4}$")  # e.g. "springer.com"
VOL_ISSUE_RE = re.compile(r"(\d+)\s*[（(](\d+)[)）]")  # 7(5) or 7（5）
PAGES_RE = re.compile(r"(?<!\d)(\d{1,5})\s*[-–]\s*(\d{1,5})(?!\d)")  # 35-46

# CrossRef type → GB/T 7714 文献类型标识
_TYPE_MAP = {
    "journal-article": "J",
    "proceedings-article": "C",
    "book-chapter": "M",
    "book": "M",
    "dissertation": "D",
    "thesis": "D",
    "posted-content": "J",
}


def _extract_year(*values: object) -> str:
    for value in values:
        if not value:
            continue
        match = YEAR_PATTERN.search(str(value))
        if match:
            return match.group(1)
    return ""


def _normalize_authors(authors: str, is_zh: bool) -> str:
    """统一参考文献作者分隔符，中文文献也使用半角逗号。"""
    authors = re.sub(r"\s*[，,]\s*", ",", authors.strip())
    authors = re.sub(r"\s+", " ", authors)
    if is_zh:
        authors = authors.replace(" ,", ",").replace(", ", ",")
    return authors


def _looks_like_university(text: str) -> bool:
    if not text or JOURNAL_HINT_RE.search(text):
        return False
    return bool(UNIVERSITY_RE.search(text))


def _format_one_reference(item: dict[str, Any], index: int, is_zh: bool) -> str:
    """使用 SerpAPI + CrossRef 数据格式化单条参考文献。

    优先使用 CrossRef 补全的结构化字段（卷/期/页码/作者/期刊），
    CrossRef 未命中时降级为从 Scholar summary 正则提取。
    """
    title = item.get("title", "").strip()
    if not title:
        return ""

    publication_info = item.get("publication_info", {})
    summary = publication_info.get("summary", "")
    authors_list = publication_info.get("authors", [])

    # ── CrossRef 补全数据 ──
    cr_authors = item.get("crossref_authors", [])
    cr_journal = item.get("crossref_journal", "")
    cr_year = item.get("crossref_year", "")
    cr_volume = item.get("crossref_volume", "")
    cr_issue = item.get("crossref_issue", "")
    cr_page = item.get("crossref_page", "")
    cr_type = item.get("crossref_type", "")
    has_crossref = bool(cr_journal or cr_volume or cr_page)

    # ── 提取作者 ──
    if cr_authors:
        if len(cr_authors) > 3:
            authors = ",".join(cr_authors[:3])
            authors += ",等" if is_zh else ",et al."
        else:
            authors = ",".join(cr_authors)
    elif authors_list:
        authors = ",".join(author.get("name", "").strip() for author in authors_list[:3] if author.get("name"))
        if len(authors_list) > 3 and authors:
            authors += ",等" if is_zh else ",et al."
    elif summary and " - " in summary:
        authors = summary.split(" - ", 1)[0].strip()
    else:
        authors = ""
    authors = _normalize_authors(authors, is_zh=is_zh) if authors else ""

    # ── 解析期刊/来源/卷期页（Scholar 降级路径） ──
    journal = ""
    university = ""
    volume_issue = ""
    pages = ""

    if not has_crossref and " - " in summary:
        dash_segments = [s.strip() for s in summary.split(" - ") if s.strip()]
        info_segments = dash_segments[1:]
        if info_segments and DOMAIN_RE.match(info_segments[-1]):
            info_segments = info_segments[:-1]

        for seg in info_segments:
            if YEAR_PATTERN.fullmatch(seg.strip()):
                continue
            if _looks_like_university(seg):
                university = seg
                continue
            sub_parts = [p.strip() for p in seg.split(",") if p.strip()]
            for sp in sub_parts:
                if YEAR_PATTERN.fullmatch(sp):
                    continue
                vol_match = VOL_ISSUE_RE.search(sp)
                if vol_match and not volume_issue:
                    volume_issue = vol_match.group(0)
                    continue
                page_match = PAGES_RE.search(sp)
                if page_match and not pages:
                    pages = f"{page_match.group(1)}-{page_match.group(2)}"
                    continue
                if not journal:
                    journal = sp

    # ── 确定最终使用的字段 ──
    final_journal = cr_journal or journal
    final_year = cr_year or _extract_year(
        summary,
        item.get("snippet", ""),
        item.get("publication_date", ""),
    )
    if not final_year:
        return ""

    final_volume = cr_volume or ""
    final_issue = cr_issue or ""
    final_page = cr_page or pages
    # 合并卷期: 如果有 CrossRef 数据按 volume(issue) 组装
    if final_volume and final_issue:
        final_vol_issue = f"{final_volume}({final_issue})"
    elif final_volume:
        final_vol_issue = final_volume
    elif not has_crossref and volume_issue:
        final_vol_issue = volume_issue
    else:
        final_vol_issue = ""

    # ── 确定文献类型 ──
    if final_journal:
        doc_marker = "J"
    elif cr_type:
        doc_marker = _TYPE_MAP.get(cr_type, "J")
    elif university and not final_journal:
        doc_marker = "D"
    else:
        doc_marker = "J"

    is_dissertation = doc_marker == "D"

    # ── 组装引用格式 (GB/T 7714 风格) ──
    parts: list[str] = []
    if authors:
        parts.append(authors)

    parts.append(f"{title}[{doc_marker}]")

    if is_dissertation:
        # 格式: 作者.标题[D].大学,年份.
        source = university or final_journal
        parts.append(f"{source},{final_year}" if source else final_year)
    else:
        # 格式: 作者.标题[J].期刊,年份,卷(期):页码.
        if not final_vol_issue and not final_page:
            logger.debug("跳过缺卷期页码的期刊文献: %s", title[:80])
            return ""
        detail_items: list[str] = []
        if final_journal:
            detail_items.append(final_journal)
        detail_items.append(final_year)
        if final_vol_issue:
            detail_items.append(final_vol_issue)
        detail_str = ",".join(detail_items)
        if final_page:
            detail_str += f":{final_page}"
        parts.append(detail_str)

    body = ".".join(parts).strip()
    if not body.endswith("."):
        body += "."
    return f"[{index}]{body}"


async def _filter_results(
    llm: BaseChatModel,
    title: str,
    results: list[dict[str, Any]],
    label: str,
    *,
    keep_count: int = 10,
    fallback_num: int = 5,
) -> list[dict[str, Any]]:
    """基于标题和 summary 进行相关性筛选，失败则取前 N 条。"""
    if not results:
        return []

    try:
        chain = REFERENCE_FILTER_PROMPT | llm | StrOutputParser()
        results_json = json.dumps(
            [
                {
                    "index": i,
                    "title": item.get("title", ""),
                    "summary": item.get("publication_info", {}).get("summary", ""),
                }
                for i, item in enumerate(results)
            ],
            ensure_ascii=False,
        )
        raw = cast(
            str,
            await chain.ainvoke(
                {
                    "title": title,
                    "results_json": results_json,
                    "keep_count": keep_count,
                }
            ),
        )
        keep_indices = json.loads(raw.strip()).get("keep", [])
        return [results[i] for i in keep_indices if isinstance(i, int) and i < len(results)]
    except Exception as exc:  # noqa: BLE001
        logger.warning("%s 文献筛选失败，回退前几条: %s", label, exc)
        return results[:fallback_num]


async def generate_references(
    title: str,
    outline: str,
    wxnum: int = 25,
    include_english: bool = True,
) -> str:
    """
    生成参考文献列表。
    SERPAPI_KEY 未配置时直接返回空字符串。
    """
    settings = get_settings()
    if not settings.serpapi_key:
        logger.info("SERPAPI_KEY 未配置，跳过参考文献生成")
        return ""

    llm = create_llm(model=settings.thesis_outline_model, temperature=0, max_tokens=512)

    try:
        keyword_chain = REFERENCE_KEYWORD_PROMPT | llm | StrOutputParser()
        raw_keywords = await keyword_chain.ainvoke({"title": title, "outline": outline[:2000]})
        keyword_data = json.loads(raw_keywords.strip())
        zh_query = keyword_data.get("zh") or title
        en_queries = keyword_data.get("en") or [title]
        if not isinstance(en_queries, list):
            en_queries = [title]
        en_queries = [str(query).strip() for query in en_queries[:2] if str(query).strip()]
        if not en_queries:
            en_queries = [title]
    except Exception as exc:  # noqa: BLE001
        logger.warning("参考文献关键词提取失败，使用标题兜底: %s", exc)
        zh_query = title
        en_queries = [title]

    # 搜索量加大缓冲：考虑去重 + 无年份淘汰的损耗
    zh_search_num = min(max(wxnum + 10, 20), 40)
    en_search_num = min(max(wxnum, 15), 30)
    search_tasks = [_search_scholar(zh_query, num=zh_search_num)]
    if include_english:
        search_tasks.extend(_search_scholar(query, num=en_search_num) for query in en_queries)
    grouped_results = await asyncio.gather(*search_tasks)

    zh_results = grouped_results[0]

    en_results: list[dict[str, Any]] = []
    if include_english:
        for group in grouped_results[1:]:
            en_results.extend(group)

    seen_titles: set[str] = set()

    def _dedup(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        deduped: list[dict[str, Any]] = []
        for item in items:
            title_key = _title_key(item)
            if not title_key or title_key in seen_titles:
                continue
            seen_titles.add(title_key)
            deduped.append(item)
        return deduped

    zh_results = _dedup(zh_results)
    en_results = _dedup(en_results)

    if not zh_results and not en_results:
        logger.warning("参考文献搜索结果为空，跳过生成")
        return ""

    # 动态 1:2 比例（英:中），并加缓冲应对无年份损耗
    target_total = max(1, wxnum)
    if include_english:
        target_en = max(3, round(target_total / 3))
        target_zh = target_total - target_en
    else:
        target_en = 0
        target_zh = target_total

    # LLM 筛选：多要一些，为无年份淘汰留余量
    buffer = 5
    if include_english:
        zh_filtered, en_filtered = await asyncio.gather(
            _filter_results(llm, title, zh_results, "中文", keep_count=target_zh + buffer, fallback_num=max(10, wxnum)),
            _filter_results(
                llm, title, en_results, "英文", keep_count=target_en + buffer, fallback_num=max(8, min(wxnum, 15))
            ),
        )
    else:
        zh_filtered = await _filter_results(
            llm, title, zh_results, "中文", keep_count=target_zh + buffer, fallback_num=max(10, wxnum)
        )
        en_filtered = []

    # ── CrossRef 补全卷期页码 ──
    all_filtered = zh_filtered + en_filtered
    try:
        from services.thesis.crossref_client import enrich_with_crossref

        await enrich_with_crossref(all_filtered)
    except Exception as exc:  # noqa: BLE001
        logger.warning("CrossRef 补全整体失败，降级使用 Scholar 数据: %s", exc)

    used_title_keys: set[str] = set()
    lines: list[str] = []
    idx = 1

    def _append_formatted(items: list[dict[str, Any]], limit: int, *, is_zh: bool) -> None:
        nonlocal idx
        for item in items:
            if len(lines) >= target_total or limit <= 0:
                break
            title_key = _title_key(item)
            if not title_key or title_key in used_title_keys:
                continue
            line = _format_one_reference(item, idx, is_zh=is_zh)
            if not line:
                continue
            lines.append(line)
            used_title_keys.add(title_key)
            idx += 1
            limit -= 1

    _append_formatted(zh_filtered, target_zh, is_zh=True)
    if include_english:
        _append_formatted(en_filtered, target_en, is_zh=False)
    # 数量不够时从原始结果回补
    if len(lines) < target_total:
        # 回补的也需要 CrossRef 补全
        zh_remaining = [item for item in zh_results if _title_key(item) not in used_title_keys]
        en_remaining = [item for item in en_results if _title_key(item) not in used_title_keys]
        backfill = zh_remaining + en_remaining
        if backfill:
            try:
                from services.thesis.crossref_client import enrich_with_crossref

                await enrich_with_crossref(backfill)
            except Exception:  # noqa: BLE001
                pass
        _append_formatted(zh_remaining, target_total - len(lines), is_zh=True)
        if include_english and len(lines) < target_total:
            _append_formatted(en_remaining, target_total - len(lines), is_zh=False)

    return "\n".join(lines)
