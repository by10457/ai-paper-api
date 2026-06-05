"""万方开放平台参考文献生成服务。"""

import asyncio
import json
import logging
import re
from typing import Any, cast

import httpx
from langchain_core.output_parsers import StrOutputParser

from core.config import get_settings
from llm.client import create_configured_llm
from llm.prompts.thesis_reference_prompt import REFERENCE_KEYWORD_PROMPT
from services.thesis.generation.concurrency import text_short_slot, wfdata_slot

logger = logging.getLogger(__name__)

WFDATA_COLLECTIONS = ["OpenPeriodical"]
WFDATA_RETURNED_FIELDS = [
    "Title",
    "Creator",
    "PublishYear",
    "Type",
    "PeriodicalTitle",
    "ConferenceName",
    "DOI",
    "Volum",
    "Volume",
    "Issue",
    "Page",
    "Publisher",
    "OriginalOrganization",
    "AuthorOrg",
    "CitedCount",
    "SourceDB",
]

_TYPE_MARKER_MAP = {
    "Periodical": "J",
    "OpenPeriodical": "J",
    "Thesis": "D",
    "OpenThesis": "D",
    "Conference": "C",
    "OpenConference": "C",
    "Book": "M",
    "Patent": "P",
    "Standard": "S",
}


def _scalar_from_value(value: dict[str, Any]) -> str:
    """从万方 protobuf 风格字段中提取单个标量值。"""

    if "stringValue" in value:
        return str(value["stringValue"]).strip()
    if "numberValue" in value:
        number_value = value["numberValue"]
        return str(int(number_value)) if isinstance(number_value, float) and number_value.is_integer() else str(number_value)
    if "boolValue" in value:
        return str(value["boolValue"])
    return ""


def _field_values(fields: dict[str, Any], name: str) -> list[str]:
    """读取万方 fields 中的字段值，兼容 stringValue、numberValue 和 listValue。"""

    raw_value = fields.get(name)
    if not isinstance(raw_value, dict):
        return []

    list_value = raw_value.get("listValue")
    if isinstance(list_value, dict):
        values = list_value.get("values", [])
        if isinstance(values, list):
            return [text for item in values if isinstance(item, dict) and (text := _scalar_from_value(item))]

    scalar = _scalar_from_value(raw_value)
    return [scalar] if scalar else []


def _first_field(fields: dict[str, Any], *names: str) -> str:
    """按字段名顺序读取第一个非空值。"""

    for name in names:
        values = _field_values(fields, name)
        if values:
            return values[0]
    return ""


def _contains_chinese(text: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in text)


def _choose_language_value(values: list[str], *, prefer_english: bool) -> str:
    """从万方多值字段中选择中文或英文值。"""

    if not values:
        return ""

    if prefer_english:
        return next((value for value in values if not _contains_chinese(value)), values[0])
    return next((value for value in values if _contains_chinese(value)), values[0])


def _choose_field(fields: dict[str, Any], *names: str, prefer_english: bool) -> str:
    for name in names:
        values = _field_values(fields, name)
        selected = _choose_language_value(values, prefer_english=prefer_english)
        if selected:
            return selected
    return ""


def _normalize_query(query: str) -> str:
    """把 LLM 提取出的空格分词转换成万方可识别的 AND 查询。"""

    query = query.strip()
    if not query:
        return ""
    if any(operator in query.upper() for operator in (" AND ", " OR ", " NOT ", "(", ")")):
        return query
    parts = [part for part in re.split(r"\s+", query) if part]
    return " AND ".join(parts) if len(parts) > 1 else query


def _with_language_filter(query: str, language: str) -> str:
    normalized_query = _normalize_query(query)
    if not normalized_query:
        return f"Language:{language}"
    return f"({normalized_query}) AND Language:{language}"


def _merge_queries_with_or(queries: list[str]) -> str:
    normalized_queries = [_normalize_query(query) for query in queries if query.strip()]
    if not normalized_queries:
        return ""
    if len(normalized_queries) == 1:
        return normalized_queries[0]
    return " OR ".join(f"({query})" for query in normalized_queries)


def _title_key(item: dict[str, Any]) -> str:
    return str(item.get("title_key") or item.get("title") or "").strip().lower()


def _build_title_key(titles: list[str]) -> str:
    title_keys = [re.sub(r"\s+", "", title.strip().lower()) for title in titles if title.strip()]
    return "|".join(sorted(set(title_keys)))


def _to_int(value: str) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


async def _extract_keyword_queries(title: str, outline: str) -> tuple[str, list[str]]:
    """基于题目和大纲提取中英文检索词，失败时用标题兜底。"""

    try:
        llm = await create_configured_llm("outline", temperature=0, max_tokens=512)
        keyword_chain = REFERENCE_KEYWORD_PROMPT | llm | StrOutputParser()
        async with text_short_slot():
            raw_keywords = await keyword_chain.ainvoke({"title": title, "outline": outline[:2000]})

        keyword_data = json.loads(str(raw_keywords).strip())
        zh_query = str(keyword_data.get("zh") or title).strip() or title
        en_queries = keyword_data.get("en") or [title]
        if not isinstance(en_queries, list):
            en_queries = [title]
        normalized_en_queries = [str(query).strip() for query in en_queries[:2] if str(query).strip()]
        return zh_query, normalized_en_queries or [title]
    except Exception as exc:  # noqa: BLE001
        logger.warning("万方参考文献关键词提取失败，使用标题兜底: %s", exc)
        return title, [title]


def _build_search_payload(query: str, rows: int, *, language: str) -> dict[str, Any]:
    return {
        "collections": WFDATA_COLLECTIONS,
        "query": _with_language_filter(query, language),
        "returned_fields": WFDATA_RETURNED_FIELDS,
        "rows": min(max(rows, 1), 100),
        "sort": {
            "sorts": [
                {"by": "CitedCount", "order": "DESC"},
                {"by": "PublishYear", "order": "DESC"},
            ]
        },
    }


async def _search_wfdata(query: str, rows: int, *, language: str) -> list[dict[str, Any]]:
    """调用万方文献检索接口，失败返回空列表。"""

    settings = get_settings()
    if not settings.wfdata_api_key:
        logger.info("WFDATA_API_KEY 未配置，跳过万方参考文献检索")
        return []

    try:
        async with wfdata_slot(), httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(
                settings.wfdata_api_url,
                headers={
                    "Content-Type": "application/json",
                    "X-Ca-AppKey": settings.wfdata_api_key,
                },
                json=_build_search_payload(query, rows, language=language),
            )
            response.raise_for_status()
            payload = cast(dict[str, Any], response.json())
            documents = payload.get("documents", [])
            return cast(list[dict[str, Any]], documents if isinstance(documents, list) else [])
    except Exception as exc:  # noqa: BLE001
        logger.warning("万方参考文献检索失败 query=%r: %s", query, exc)
        return []


def _normalize_wf_document(document: dict[str, Any], *, prefer_english: bool) -> dict[str, Any]:
    fields = document.get("fields", {})
    fields = fields if isinstance(fields, dict) else {}
    resource_type = str(document.get("resourceType") or "")
    titles = _field_values(fields, "Title")
    title = _choose_language_value(titles, prefer_english=prefer_english)
    if title and prefer_english and _contains_chinese(title):
        title = ""
    if title and not prefer_english and not _contains_chinese(title):
        title = ""

    return {
        "title": title,
        "title_key": _build_title_key(titles),
        "language": "en" if prefer_english else "zh",
        "authors": _field_values(fields, "Creator"),
        "year": _first_field(fields, "PublishYear"),
        "type": _first_field(fields, "Type") or resource_type,
        "journal": _choose_field(fields, "PeriodicalTitle", prefer_english=prefer_english),
        "conference": _choose_field(fields, "ConferenceName", prefer_english=prefer_english),
        "volume": _first_field(fields, "Volum", "Volume"),
        "issue": _first_field(fields, "Issue"),
        "page": _first_field(fields, "Page"),
        "publisher": _choose_field(fields, "Publisher", prefer_english=prefer_english),
        "organization": _choose_field(fields, "OriginalOrganization", "AuthorOrg", prefer_english=prefer_english),
        "doi": _first_field(fields, "DOI"),
        "cited_count": _to_int(_first_field(fields, "CitedCount")),
    }


def _document_marker(item: dict[str, Any]) -> str:
    doc_type = str(item.get("type") or "")
    for key, marker in _TYPE_MARKER_MAP.items():
        if key.lower() in doc_type.lower():
            return marker
    if item.get("journal"):
        return "J"
    if item.get("conference"):
        return "C"
    if item.get("organization") and not item.get("journal"):
        return "D"
    return "J"


def _format_authors(authors: list[str], *, prefer_english: bool) -> str:
    clean_authors = [author.strip().replace("，", ",") for author in authors if author.strip()]
    if not clean_authors:
        return ""
    if len(clean_authors) > 3:
        suffix = ",et al." if prefer_english else ",等"
        return ",".join(clean_authors[:3]) + suffix
    return ",".join(clean_authors)


def _format_source_detail(item: dict[str, Any], marker: str) -> str:
    year = str(item.get("year") or "").strip()
    if marker == "D":
        source = str(item.get("organization") or item.get("publisher") or "").strip()
        return f"{source},{year}" if source and year else source or year

    if marker == "C":
        source = str(item.get("conference") or item.get("publisher") or item.get("journal") or "").strip()
    else:
        source = str(item.get("journal") or item.get("publisher") or item.get("conference") or "").strip()

    volume = str(item.get("volume") or "").strip()
    issue = str(item.get("issue") or "").strip()
    page = str(item.get("page") or "").strip()

    detail_items = [value for value in (source, year) if value]
    if volume and issue:
        detail_items.append(f"{volume}({issue})")
    elif volume:
        detail_items.append(volume)
    elif issue:
        detail_items.append(f"({issue})")

    detail = ",".join(detail_items)
    if page:
        detail += f":{page}" if detail else page
    return detail


def _format_wf_reference(item: dict[str, Any], index: int) -> str:
    title = str(item.get("title") or "").strip()
    year = str(item.get("year") or "").strip()
    if not title or not year:
        return ""

    marker = _document_marker(item)
    authors = _format_authors(
        cast(list[str], item.get("authors") or []),
        prefer_english=item.get("language") == "en",
    )
    detail = _format_source_detail(item, marker)

    parts: list[str] = []
    if authors:
        parts.append(authors)
    parts.append(f"{title}[{marker}]")
    if detail:
        parts.append(detail)

    body = ".".join(parts).strip()
    if not body.endswith("."):
        body += "."
    return f"[{index}]{body}"


def _dedup_documents(
    documents: list[dict[str, Any]],
    *,
    prefer_english: bool,
    seen_titles: set[str] | None = None,
) -> list[dict[str, Any]]:
    if seen_titles is None:
        seen_titles = set()

    items: list[dict[str, Any]] = []
    for document in documents:
        item = _normalize_wf_document(document, prefer_english=prefer_english)
        title_key = _title_key(item)
        if not title_key or title_key in seen_titles:
            continue
        seen_titles.add(title_key)
        items.append(item)
    return sorted(items, key=lambda item: (item.get("cited_count", 0), item.get("year", "")), reverse=True)


def _append_formatted_references(lines: list[str], items: list[dict[str, Any]], target_count: int) -> None:
    for item in items:
        if target_count <= 0:
            break
        line = _format_wf_reference(item, len(lines) + 1)
        if not line:
            continue
        lines.append(line)
        target_count -= 1


def _search_rows_for_target(target_count: int) -> int:
    if target_count <= 0:
        return 0
    return min(target_count + max(2, round(target_count * 0.2)), 100)


async def generate_references(
    title: str,
    outline: str,
    wxnum: int = 25,
    include_english: bool = True,
) -> str:
    """使用万方开放平台生成参考文献列表。"""

    target_total = max(1, wxnum)
    zh_query, en_queries = await _extract_keyword_queries(title, outline)
    if include_english:
        target_en = max(3, round(target_total / 3))
        target_zh = target_total - target_en
    else:
        target_en = 0
        target_zh = target_total

    search_tasks = [_search_wfdata(zh_query, _search_rows_for_target(target_zh), language="chi")]
    if include_english:
        en_query = _merge_queries_with_or(en_queries[:2])
        search_tasks.append(_search_wfdata(en_query, _search_rows_for_target(target_en), language="eng"))

    grouped_documents = await asyncio.gather(*search_tasks)
    zh_documents = grouped_documents[0]
    en_documents = [document for group in grouped_documents[1:] for document in group]
    if not zh_documents and not en_documents:
        logger.warning("万方参考文献检索结果为空")
        return ""

    seen_titles: set[str] = set()
    zh_items = _dedup_documents(zh_documents, prefer_english=False, seen_titles=seen_titles)
    en_items = _dedup_documents(en_documents, prefer_english=True, seen_titles=seen_titles)

    lines: list[str] = []
    _append_formatted_references(lines, zh_items, target_zh)
    if include_english:
        _append_formatted_references(lines, en_items, target_en)

    return "\n".join(lines)
