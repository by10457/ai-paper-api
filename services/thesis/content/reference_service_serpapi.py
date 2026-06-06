"""
SerpAPI 参考文献生成服务。

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
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any, cast

import httpx
from langchain_core.language_models import BaseChatModel
from langchain_core.output_parsers import StrOutputParser

from core.config import get_settings
from llm.client import create_configured_llm
from llm.prompts.thesis_reference_prompt import (
    REFERENCE_FILTER_PROMPT,
    REFERENCE_SCHOLAR_KEYWORD_PROMPT,
)
from services.thesis.generation.concurrency import crossref_slot, serpapi_slot, text_short_slot
from services.thesis.generation.progress import record_process_detail

logger = logging.getLogger(__name__)

SERPAPI_BASE = "https://serpapi.com/search"
CROSSREF_API = "https://api.crossref.org/works"
CROSSREF_SELECT_FIELDS = "title,author,container-title,published,volume,issue,page,type"
CROSSREF_TITLE_SIMILARITY_THRESHOLD = 0.55

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


@dataclass(frozen=True)
class ScholarKeywordQueries:
    """SerpAPI Google Scholar 检索关键词。"""

    zh_query: str
    en_queries: list[str]


@dataclass(frozen=True)
class ReferenceTargets:
    """参考文献目标数量拆分。"""

    total: int
    zh: int
    en: int


@dataclass(frozen=True)
class ScholarSearchResults:
    """SerpAPI 检索结果及本次请求规模。"""

    zh_results: list[dict[str, Any]]
    en_results: list[dict[str, Any]]
    zh_search_num: int
    en_search_num: int


@dataclass(frozen=True)
class ScholarFallbackFields:
    """从 Scholar summary 中解析出的降级来源字段。"""

    journal: str = ""
    university: str = ""
    volume_issue: str = ""
    pages: str = ""


async def _search_scholar(query: str, num: int = 8) -> list[dict[str, Any]]:
    """调用 SerpAPI Google Scholar，失败返回空列表。"""
    api_key = get_settings().serpapi_key
    try:
        async with serpapi_slot(), httpx.AsyncClient(timeout=20.0) as client:
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


def _format_authors_from_sources(
    *,
    crossref_authors: list[str],
    scholar_authors: list[dict[str, Any]],
    summary: str,
    is_zh: bool,
) -> str:
    """按 CrossRef、Scholar 作者列表、summary 的优先级提取作者。"""

    if crossref_authors:
        if len(crossref_authors) > 3:
            suffix = ",等" if is_zh else ",et al."
            return _normalize_authors(",".join(crossref_authors[:3]) + suffix, is_zh=is_zh)
        return _normalize_authors(",".join(crossref_authors), is_zh=is_zh)

    if scholar_authors:
        authors = ",".join(author.get("name", "").strip() for author in scholar_authors[:3] if author.get("name"))
        if len(scholar_authors) > 3 and authors:
            authors += ",等" if is_zh else ",et al."
        return _normalize_authors(authors, is_zh=is_zh) if authors else ""

    if summary and " - " in summary:
        return _normalize_authors(summary.split(" - ", 1)[0].strip(), is_zh=is_zh)
    return ""


def _looks_like_university(text: str) -> bool:
    if not text or JOURNAL_HINT_RE.search(text):
        return False
    return bool(UNIVERSITY_RE.search(text))


def _is_chinese(text: str) -> bool:
    """粗略判断字符串是否包含中文字符。"""
    return any("\u4e00" <= char <= "\u9fff" for char in text)


def _crossref_mailto() -> str:
    return get_settings().crossref_mailto or "noreply@example.com"


def _normalize_crossref_title(title: str) -> str:
    """归一化标题，用于 CrossRef 模糊匹配校验。"""
    return re.sub(r"[^\w]", "", title).lower()


def _is_crossref_title_matched(query_title: str, found_title: str) -> bool:
    normalized_query = _normalize_crossref_title(query_title)
    normalized_found = _normalize_crossref_title(found_title)
    if not normalized_query or not normalized_found:
        return False
    ratio = SequenceMatcher(None, normalized_query, normalized_found).ratio()
    return ratio >= CROSSREF_TITLE_SIMILARITY_THRESHOLD


async def _query_crossref_one(client: httpx.AsyncClient, title: str) -> dict[str, Any] | None:
    """用标题查询 CrossRef，匹配失败或请求失败时返回 None。"""
    async with crossref_slot():
        try:
            response = await client.get(
                CROSSREF_API,
                params={
                    "query.bibliographic": title,
                    "rows": 1,
                    "select": CROSSREF_SELECT_FIELDS,
                    "mailto": _crossref_mailto(),
                },
            )
            response.raise_for_status()
            payload = cast(dict[str, Any], response.json())
            items = cast(list[dict[str, Any]], payload.get("message", {}).get("items", []))
            if not items:
                return None

            item = items[0]
            found_title = (item.get("title") or [""])[0]
            if not _is_crossref_title_matched(title, found_title):
                logger.debug("CrossRef 标题不匹配，跳过: query=%r found=%r", title[:50], found_title[:50])
                return None
            return item
        except Exception as exc:  # noqa: BLE001
            logger.debug("CrossRef 查询失败 title=%r: %s", title[:50], exc)
            return None


def _extract_crossref_fields(item: dict[str, Any]) -> dict[str, Any]:
    """从 CrossRef 返回项提取参考文献格式化需要的字段。"""
    author_names: list[str] = []
    for author in item.get("author", [])[:5]:
        given = author.get("given", "").strip()
        family = author.get("family", "").strip()
        if given and family:
            author_names.append(f"{family} {given}" if _is_chinese(family) else f"{given} {family}")
        elif family:
            author_names.append(family)

    date_parts = item.get("published", {}).get("date-parts", [[]])
    year = str(date_parts[0][0]) if date_parts and date_parts[0] else ""

    return {
        "crossref_authors": author_names,
        "crossref_journal": (item.get("container-title") or [""])[0],
        "crossref_year": year,
        "crossref_volume": item.get("volume", ""),
        "crossref_issue": item.get("issue", ""),
        "crossref_page": item.get("page", ""),
        "crossref_type": item.get("type", ""),
    }


def _extract_scholar_fallback_fields(summary: str, *, has_crossref: bool) -> ScholarFallbackFields:
    """从 Scholar summary 中解析期刊、学校、卷期和页码。"""

    if has_crossref or " - " not in summary:
        return ScholarFallbackFields()

    journal = ""
    university = ""
    volume_issue = ""
    pages = ""
    dash_segments = [segment.strip() for segment in summary.split(" - ") if segment.strip()]
    info_segments = dash_segments[1:]
    if info_segments and DOMAIN_RE.match(info_segments[-1]):
        info_segments = info_segments[:-1]

    for segment in info_segments:
        if YEAR_PATTERN.fullmatch(segment.strip()):
            continue
        if _looks_like_university(segment):
            university = segment
            continue
        for part in [value.strip() for value in segment.split(",") if value.strip()]:
            if YEAR_PATTERN.fullmatch(part):
                continue
            volume_match = VOL_ISSUE_RE.search(part)
            if volume_match and not volume_issue:
                volume_issue = volume_match.group(0)
                continue
            page_match = PAGES_RE.search(part)
            if page_match and not pages:
                pages = f"{page_match.group(1)}-{page_match.group(2)}"
                continue
            if not journal:
                journal = part
    return ScholarFallbackFields(journal=journal, university=university, volume_issue=volume_issue, pages=pages)


def _resolve_volume_issue(volume: str, issue: str, fallback_volume_issue: str, *, has_crossref: bool) -> str:
    """合并卷期字段，CrossRef 优先，Scholar summary 作为降级来源。"""

    if volume and issue:
        return f"{volume}({issue})"
    if volume:
        return volume
    if not has_crossref and fallback_volume_issue:
        return fallback_volume_issue
    return ""


def _resolve_doc_marker(journal: str, crossref_type: str, university: str) -> str:
    """推断 GB/T 7714 文献类型标识。"""

    if journal:
        return "J"
    if crossref_type:
        return _TYPE_MAP.get(crossref_type, "J")
    if university:
        return "D"
    return "J"


def _build_reference_body(
    *,
    authors: str,
    title: str,
    marker: str,
    journal: str,
    year: str,
    volume_issue: str,
    page: str,
    university: str,
) -> str:
    """组装 GB/T 7714 风格参考文献正文，不含编号。"""

    parts: list[str] = []
    if authors:
        parts.append(authors)
    parts.append(f"{title}[{marker}]")

    if marker == "D":
        source = university or journal
        parts.append(f"{source},{year}" if source else year)
    else:
        if not volume_issue and not page:
            return ""
        detail_items: list[str] = []
        if journal:
            detail_items.append(journal)
        detail_items.append(year)
        if volume_issue:
            detail_items.append(volume_issue)
        detail = ",".join(detail_items)
        if page:
            detail += f":{page}"
        parts.append(detail)

    body = ".".join(parts).strip()
    return body if body.endswith(".") else body + "."


async def _enrich_with_crossref(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """批量用 CrossRef 补全文献的作者、期刊、年份、卷期和页码。"""
    if not items:
        return items

    async with httpx.AsyncClient(timeout=12.0) as client:
        results = await asyncio.gather(*[_query_crossref_one(client, item.get("title", "")) for item in items])

    enriched_count = 0
    for item, crossref_item in zip(items, results, strict=True):
        if crossref_item is None:
            continue
        item.update(_extract_crossref_fields(crossref_item))
        enriched_count += 1

    logger.info("CrossRef 补全完成: %d/%d 条匹配成功", enriched_count, len(items))
    return items


def _format_one_reference(item: dict[str, Any], index: int, is_zh: bool) -> str:
    """使用 SerpAPI + CrossRef 数据格式化单条参考文献。

    优先使用 CrossRef 补全的结构化字段（卷/期/页码/作者/期刊），
    CrossRef 未命中时降级为从 Scholar summary 正则提取。
    """
    title = str(item.get("title", "")).strip()
    if not title:
        return ""

    publication_info = item.get("publication_info", {})
    publication_info = publication_info if isinstance(publication_info, dict) else {}
    summary = str(publication_info.get("summary", ""))
    scholar_authors = cast(list[dict[str, Any]], publication_info.get("authors", []))
    crossref_authors = cast(list[str], item.get("crossref_authors", []))
    crossref_journal = str(item.get("crossref_journal", ""))
    crossref_year = str(item.get("crossref_year", ""))
    crossref_volume = str(item.get("crossref_volume", ""))
    crossref_issue = str(item.get("crossref_issue", ""))
    crossref_page = str(item.get("crossref_page", ""))
    crossref_type = str(item.get("crossref_type", ""))
    has_crossref = bool(crossref_journal or crossref_volume or crossref_page)

    fallback = _extract_scholar_fallback_fields(summary, has_crossref=has_crossref)
    journal = crossref_journal or fallback.journal
    year = crossref_year or _extract_year(
        summary,
        item.get("snippet", ""),
        item.get("publication_date", ""),
    )
    if not year:
        return ""

    marker = _resolve_doc_marker(journal, crossref_type, fallback.university)
    volume_issue = _resolve_volume_issue(
        crossref_volume,
        crossref_issue,
        fallback.volume_issue,
        has_crossref=has_crossref,
    )
    body = _build_reference_body(
        authors=_format_authors_from_sources(
            crossref_authors=crossref_authors,
            scholar_authors=scholar_authors,
            summary=summary,
            is_zh=is_zh,
        ),
        title=title,
        marker=marker,
        journal=journal,
        year=year,
        volume_issue=volume_issue,
        page=crossref_page or fallback.pages,
        university=fallback.university,
    )
    if not body:
        logger.debug("跳过缺卷期页码的期刊文献: %s", title[:80])
        return ""
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
        async with text_short_slot():
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


async def _extract_scholar_keyword_queries(llm: BaseChatModel, title: str, outline: str) -> ScholarKeywordQueries:
    """提取 Google Scholar 检索词，失败时使用标题兜底。"""

    try:
        keyword_chain = REFERENCE_SCHOLAR_KEYWORD_PROMPT | llm | StrOutputParser()
        async with text_short_slot():
            raw_keywords = cast(str, await keyword_chain.ainvoke({"title": title, "outline": outline[:2000]}))
        keyword_data = json.loads(raw_keywords.strip())
        if not isinstance(keyword_data, dict):
            return ScholarKeywordQueries(zh_query=title, en_queries=[title])

        zh_query = str(keyword_data.get("zh") or title).strip() or title
        en_queries = keyword_data.get("en") or [title]
        if not isinstance(en_queries, list):
            en_queries = [title]
        normalized_en_queries = [str(query).strip() for query in en_queries[:2] if str(query).strip()]
        return ScholarKeywordQueries(zh_query=zh_query, en_queries=normalized_en_queries or [title])
    except Exception as exc:  # noqa: BLE001
        logger.warning("参考文献关键词提取失败，使用标题兜底: %s", exc)
        return ScholarKeywordQueries(zh_query=title, en_queries=[title])


def _build_reference_targets(wxnum: int, *, include_chinese: bool, include_english: bool) -> ReferenceTargets:
    """按中英文开关计算参考文献目标数量。"""

    target_total = max(1, wxnum)
    if include_chinese and include_english:
        target_en = max(3, round(target_total / 3))
        return ReferenceTargets(total=target_total, zh=target_total - target_en, en=target_en)
    if include_english:
        return ReferenceTargets(total=target_total, zh=0, en=target_total)
    return ReferenceTargets(total=target_total, zh=target_total, en=0)


async def _search_scholar_results(
    queries: ScholarKeywordQueries,
    wxnum: int,
    *,
    include_chinese: bool,
    include_english: bool,
) -> ScholarSearchResults:
    """按中英文检索开关调用 SerpAPI，并按语言归并结果。"""

    zh_search_num = min(max(wxnum + 10, 20), 40)
    en_search_num = min(max(wxnum, 15), 30)
    search_labels: list[str] = []
    search_tasks = []
    if include_chinese:
        search_labels.append("zh")
        search_tasks.append(_search_scholar(queries.zh_query, num=zh_search_num))
    if include_english:
        for query in queries.en_queries:
            search_labels.append("en")
            search_tasks.append(_search_scholar(query, num=en_search_num))

    grouped_results = await asyncio.gather(*search_tasks)
    zh_results: list[dict[str, Any]] = []
    en_results: list[dict[str, Any]] = []
    for label, group in zip(search_labels, grouped_results, strict=True):
        if label == "zh":
            zh_results.extend(group)
        else:
            en_results.extend(group)
    return ScholarSearchResults(zh_results, en_results, zh_search_num, en_search_num)


def _dedup_search_results(
    zh_results: list[dict[str, Any]],
    en_results: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """按标题去重，中英文结果共享同一个标题集合。"""

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

    return _dedup(zh_results), _dedup(en_results)


async def _filter_scholar_results(
    llm: BaseChatModel,
    title: str,
    zh_results: list[dict[str, Any]],
    en_results: list[dict[str, Any]],
    targets: ReferenceTargets,
    wxnum: int,
    *,
    include_chinese: bool,
    include_english: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """调用 LLM 进行相关性筛选，并为后续无年份淘汰预留缓冲。"""

    buffer = 5
    if include_chinese and include_english:
        return await asyncio.gather(
            _filter_results(llm, title, zh_results, "中文", keep_count=targets.zh + buffer, fallback_num=max(10, wxnum)),
            _filter_results(
                llm,
                title,
                en_results,
                "英文",
                keep_count=targets.en + buffer,
                fallback_num=max(8, min(wxnum, 15)),
            ),
        )
    if include_english:
        en_filtered = await _filter_results(
            llm,
            title,
            en_results,
            "英文",
            keep_count=targets.en + buffer,
            fallback_num=max(8, min(wxnum, 15)),
        )
        return [], en_filtered

    zh_filtered = await _filter_results(
        llm,
        title,
        zh_results,
        "中文",
        keep_count=targets.zh + buffer,
        fallback_num=max(10, wxnum),
    )
    return zh_filtered, []


async def _enrich_with_crossref_best_effort(items: list[dict[str, Any]], label: str) -> None:
    """CrossRef 只是补全来源信息，失败不能中断参考文献生成。"""

    if not items:
        return
    try:
        await _enrich_with_crossref(items)
    except Exception as exc:  # noqa: BLE001
        logger.warning("%s CrossRef 补全失败，降级使用 Scholar 数据: %s", label, exc)


async def _record_scholar_keywords(
    queries: ScholarKeywordQueries,
    *,
    include_chinese: bool,
    include_english: bool,
) -> None:
    """记录 SerpAPI 关键词提取结果。"""

    await record_process_detail(
        "references",
        "已提取 SerpAPI 文献检索关键词",
        provider="serpapi",
        zh_query=queries.zh_query,
        en_queries=queries.en_queries,
        include_chinese=include_chinese,
        include_english=include_english,
    )


async def _record_scholar_search_results(
    search_results: ScholarSearchResults,
    *,
    include_chinese: bool,
    include_english: bool,
) -> None:
    """记录 SerpAPI 检索结果数量。"""

    await record_process_detail(
        "references",
        "SerpAPI 文献检索完成",
        provider="serpapi",
        zh_result_count=len(search_results.zh_results),
        en_result_count=len(search_results.en_results),
        zh_search_num=search_results.zh_search_num if include_chinese else 0,
        en_search_num=search_results.en_search_num if include_english else 0,
    )


async def _record_scholar_format_result(
    targets: ReferenceTargets,
    zh_filtered: list[dict[str, Any]],
    en_filtered: list[dict[str, Any]],
    lines: list[str],
) -> None:
    """记录 SerpAPI 参考文献最终格式化结果。"""

    await record_process_detail(
        "references",
        "参考文献格式化完成",
        provider="serpapi",
        target_total=targets.total,
        target_zh=targets.zh,
        target_en=targets.en,
        filtered_zh_count=len(zh_filtered),
        filtered_en_count=len(en_filtered),
        final_count=len(lines),
    )


def _append_formatted_references(
    lines: list[str],
    used_title_keys: set[str],
    items: list[dict[str, Any]],
    *,
    start_index: int,
    target_total: int,
    limit: int,
    is_zh: bool,
) -> int:
    """把候选文献格式化为编号行，返回下一条参考文献编号。"""

    next_index = start_index
    remaining = limit
    for item in items:
        if len(lines) >= target_total or remaining <= 0:
            break
        title_key = _title_key(item)
        if not title_key or title_key in used_title_keys:
            continue
        line = _format_one_reference(item, next_index, is_zh=is_zh)
        if not line:
            continue
        lines.append(line)
        used_title_keys.add(title_key)
        next_index += 1
        remaining -= 1
    return next_index


async def _format_scholar_references(
    zh_filtered: list[dict[str, Any]],
    en_filtered: list[dict[str, Any]],
    zh_results: list[dict[str, Any]],
    en_results: list[dict[str, Any]],
    targets: ReferenceTargets,
    *,
    include_chinese: bool,
    include_english: bool,
) -> list[str]:
    """格式化筛选结果，数量不足时从原始检索结果回补。"""

    await _enrich_with_crossref_best_effort(zh_filtered + en_filtered, "筛选文献")

    used_title_keys: set[str] = set()
    lines: list[str] = []
    next_index = 1
    if include_chinese:
        next_index = _append_formatted_references(
            lines,
            used_title_keys,
            zh_filtered,
            start_index=next_index,
            target_total=targets.total,
            limit=targets.zh,
            is_zh=True,
        )
    if include_english:
        next_index = _append_formatted_references(
            lines,
            used_title_keys,
            en_filtered,
            start_index=next_index,
            target_total=targets.total,
            limit=targets.en,
            is_zh=False,
        )

    if len(lines) >= targets.total:
        return lines

    zh_remaining = [item for item in zh_results if include_chinese and _title_key(item) not in used_title_keys]
    en_remaining = [item for item in en_results if include_english and _title_key(item) not in used_title_keys]
    await _enrich_with_crossref_best_effort(zh_remaining + en_remaining, "回补文献")
    if include_chinese:
        next_index = _append_formatted_references(
            lines,
            used_title_keys,
            zh_remaining,
            start_index=next_index,
            target_total=targets.total,
            limit=targets.total - len(lines),
            is_zh=True,
        )
    if include_english and len(lines) < targets.total:
        _append_formatted_references(
            lines,
            used_title_keys,
            en_remaining,
            start_index=next_index,
            target_total=targets.total,
            limit=targets.total - len(lines),
            is_zh=False,
        )
    return lines


async def generate_references(
    title: str,
    outline: str,
    wxnum: int = 25,
    include_english: bool = True,
    *,
    include_chinese: bool = True,
) -> str:
    """
    使用 SerpAPI + CrossRef 生成参考文献列表。
    SERPAPI_KEY 未配置时直接返回空字符串。
    """
    settings = get_settings()
    if not settings.serpapi_key:
        logger.info("SERPAPI_KEY 未配置，跳过参考文献生成")
        return ""
    if not include_chinese and not include_english:
        return ""

    llm = await create_configured_llm("outline", temperature=0, max_tokens=512)
    queries = await _extract_scholar_keyword_queries(llm, title, outline)
    await _record_scholar_keywords(queries, include_chinese=include_chinese, include_english=include_english)

    search_results = await _search_scholar_results(
        queries,
        wxnum,
        include_chinese=include_chinese,
        include_english=include_english,
    )
    await _record_scholar_search_results(
        search_results,
        include_chinese=include_chinese,
        include_english=include_english,
    )

    zh_results, en_results = _dedup_search_results(search_results.zh_results, search_results.en_results)
    if not zh_results and not en_results:
        logger.warning("参考文献搜索结果为空，跳过生成")
        return ""

    targets = _build_reference_targets(wxnum, include_chinese=include_chinese, include_english=include_english)
    zh_filtered, en_filtered = await _filter_scholar_results(
        llm,
        title,
        zh_results,
        en_results,
        targets,
        wxnum,
        include_chinese=include_chinese,
        include_english=include_english,
    )
    lines = await _format_scholar_references(
        zh_filtered,
        en_filtered,
        zh_results,
        en_results,
        targets,
        include_chinese=include_chinese,
        include_english=include_english,
    )
    await _record_scholar_format_result(targets, zh_filtered, en_filtered, lines)

    return "\n".join(lines)
