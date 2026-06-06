"""万方开放平台参考文献生成服务。"""

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from typing import Any, cast

import httpx
from langchain_core.output_parsers import StrOutputParser

from core.config import get_settings
from llm.client import create_configured_llm
from llm.prompts.thesis_reference_prompt import REFERENCE_WFDATA_KEYWORD_PROMPT
from services.thesis.generation.concurrency import text_short_slot, wfdata_slot
from services.thesis.generation.progress import record_process_detail

logger = logging.getLogger(__name__)

WFDATA_COLLECTIONS = ["OpenPeriodical"]
WFDATA_MAX_ATTEMPTS = 3
WFDATA_RETRY_BACKOFF_SECONDS = 1.5
WFDATA_RESPONSE_PREVIEW_LENGTH = 500
WFDATA_ZH_QUERY_LIMIT = 8
WFDATA_EN_QUERY_LIMIT = 6
WFDATA_BATCH_BUFFER_MULTIPLIER = 3
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


@dataclass(frozen=True)
class WfReferenceTargets:
    """万方参考文献中英文目标数量。"""

    total: int
    zh: int
    en: int


@dataclass(frozen=True)
class WfSearchResults:
    """万方中英文检索结果。"""

    zh_documents: list[dict[str, Any]]
    en_documents: list[dict[str, Any]]


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


def _append_keyword_values(queries: list[str], value: Any) -> None:
    if isinstance(value, str):
        query = value.strip()
        if query:
            queries.append(query)
        return

    if isinstance(value, list):
        for item in value:
            if isinstance(item, str) and item.strip():
                queries.append(item.strip())


def _dedup_keyword_queries(queries: list[str], fallback: str, limit: int) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for query in queries:
        normalized_query = re.sub(r"\s+", " ", query).strip()
        key = normalized_query.lower()
        if not normalized_query or key in seen:
            continue
        seen.add(key)
        deduped.append(normalized_query)
        if len(deduped) >= limit:
            break
    return deduped or [fallback]


def _collect_keyword_queries(keyword_data: dict[str, Any], fields: tuple[str, ...], fallback: str, limit: int) -> list[str]:
    queries: list[str] = []
    for field in fields:
        _append_keyword_values(queries, keyword_data.get(field))
    return _dedup_keyword_queries(queries, fallback, limit)


async def _extract_keyword_queries(title: str, outline: str) -> tuple[list[str], list[str]]:
    """基于题目和大纲提取中英文检索词，失败时用标题兜底。"""

    try:
        llm = await create_configured_llm("outline", temperature=0, max_tokens=768)
        keyword_chain = REFERENCE_WFDATA_KEYWORD_PROMPT | llm | StrOutputParser()
        async with text_short_slot():
            raw_keywords = await keyword_chain.ainvoke({"title": title, "outline": outline[:2000]})

        keyword_data = json.loads(str(raw_keywords).strip())
        if not isinstance(keyword_data, dict):
            return [title], [title]
        zh_queries = _collect_keyword_queries(
            keyword_data,
            ("zh", "zh_related", "zh_extended"),
            title,
            WFDATA_ZH_QUERY_LIMIT,
        )
        en_queries = _collect_keyword_queries(
            keyword_data,
            ("en", "en_related", "en_extended"),
            title,
            WFDATA_EN_QUERY_LIMIT,
        )
        return zh_queries, en_queries
    except Exception as exc:  # noqa: BLE001
        logger.warning("万方参考文献关键词提取失败，使用标题兜底: %s", exc)
        return [title], [title]


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


def _build_relaxed_query(query: str, language: str) -> str:
    """中文检索无结果时，去掉英文技术词后再尝试一次。"""

    if language != "chi":
        return ""

    relaxed_query = re.sub(r"[A-Za-z][A-Za-z0-9_.+#/-]*", " ", query)
    relaxed_query = re.sub(r"\s+", " ", relaxed_query).strip()
    if not relaxed_query or relaxed_query == query.strip() or not _contains_chinese(relaxed_query):
        return ""
    return relaxed_query


def _build_search_payloads(query: str, rows: int, *, language: str) -> list[dict[str, Any]]:
    payloads = [_build_search_payload(query, rows, language=language)]
    relaxed_query = _build_relaxed_query(query, language)
    if relaxed_query:
        relaxed_payload = _build_search_payload(relaxed_query, rows, language=language)
        if relaxed_payload["query"] != payloads[0]["query"]:
            payloads.append(relaxed_payload)
    return payloads


def _build_wfdata_headers(api_key: str) -> dict[str, str]:
    return {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "X-Ca-AppKey": api_key,
    }


def _build_wfdata_timeout() -> httpx.Timeout:
    return httpx.Timeout(timeout=30.0, connect=10.0, read=30.0, write=10.0, pool=10.0)


def _response_preview(response: httpx.Response) -> str:
    text = response.text.replace("\n", " ").strip()
    if len(text) <= WFDATA_RESPONSE_PREVIEW_LENGTH:
        return text
    return text[:WFDATA_RESPONSE_PREVIEW_LENGTH] + "..."


def _parse_search_documents(response: httpx.Response) -> list[dict[str, Any]]:
    payload = response.json()
    if not isinstance(payload, dict):
        logger.warning("万方参考文献响应不是 JSON 对象: status=%s, preview=%r", response.status_code, _response_preview(response))
        return []

    documents = payload.get("documents", [])
    if not isinstance(documents, list):
        logger.warning("万方参考文献响应缺少 documents 列表: keys=%s, preview=%r", list(payload.keys()), _response_preview(response))
        return []
    return cast(list[dict[str, Any]], documents)


def _log_wfdata_search_request(
    *,
    attempt: int,
    candidate: int,
    candidate_count: int,
    url: str,
    language: str,
    rows: int,
    payload: dict[str, Any],
) -> None:
    logger.info(
        "万方参考文献检索请求: candidate=%s/%s, attempt=%s/%s, language=%s, rows=%s, url=%s, query=%r",
        candidate,
        candidate_count,
        attempt,
        WFDATA_MAX_ATTEMPTS,
        language,
        payload.get("rows", rows),
        url,
        payload.get("query"),
    )


def _log_wfdata_search_response(
    *,
    response: httpx.Response,
    language: str,
    requested_rows: int,
    document_count: int,
) -> None:
    logger.info(
        "万方参考文献检索响应: language=%s, requested_rows=%s, status=%s, documents=%s, preview=%r",
        language,
        requested_rows,
        response.status_code,
        document_count,
        _response_preview(response),
    )


def _log_wfdata_http_error(
    exc: httpx.HTTPStatusError,
    *,
    candidate: int,
    candidate_count: int,
    attempt: int,
    language: str,
    payload: dict[str, Any],
) -> None:
    """记录万方 HTTP 状态码错误。"""

    logger.warning(
        "万方参考文献检索 HTTP 失败: candidate=%s/%s, attempt=%s/%s, language=%s, status=%s, query=%r, preview=%r",
        candidate,
        candidate_count,
        attempt,
        WFDATA_MAX_ATTEMPTS,
        language,
        exc.response.status_code,
        payload.get("query"),
        _response_preview(exc.response),
    )


def _log_wfdata_connection_error(
    exc: Exception,
    *,
    candidate: int,
    candidate_count: int,
    attempt: int,
    language: str,
    payload: dict[str, Any],
) -> None:
    """记录万方连接异常；重试成功时这类日志只作为过程信息。"""

    logger.info(
        "万方参考文献检索连接异常: candidate=%s/%s, attempt=%s/%s, language=%s, rows=%s, query=%r, error_type=%s, error=%s",
        candidate,
        candidate_count,
        attempt,
        WFDATA_MAX_ATTEMPTS,
        language,
        payload.get("rows"),
        payload.get("query"),
        type(exc).__name__,
        exc,
    )


def _log_wfdata_parse_error(
    exc: Exception,
    *,
    candidate: int,
    candidate_count: int,
    attempt: int,
    language: str,
    payload: dict[str, Any],
) -> None:
    """记录万方响应解析错误。"""

    logger.warning(
        "万方参考文献检索解析异常: candidate=%s/%s, attempt=%s/%s, language=%s, rows=%s, query=%r, error_type=%s, error=%s",
        candidate,
        candidate_count,
        attempt,
        WFDATA_MAX_ATTEMPTS,
        language,
        payload.get("rows"),
        payload.get("query"),
        type(exc).__name__,
        exc,
    )


async def _search_wfdata_payload(
    *,
    url: str,
    headers: dict[str, str],
    timeout: httpx.Timeout,
    payload: dict[str, Any],
    candidate: int,
    candidate_count: int,
    language: str,
    rows: int,
) -> tuple[list[dict[str, Any]] | None, Exception | None]:
    """检索单个万方查询载荷；None 表示 HTTP 或解析错误应终止本轮检索。"""

    last_error: Exception | None = None
    for attempt in range(1, WFDATA_MAX_ATTEMPTS + 1):
        _log_wfdata_search_request(
            attempt=attempt,
            candidate=candidate,
            candidate_count=candidate_count,
            url=url,
            language=language,
            rows=rows,
            payload=payload,
        )

        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, trust_env=False) as client:
                response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            documents = _parse_search_documents(response)
            _log_wfdata_search_response(
                response=response,
                language=language,
                requested_rows=cast(int, payload["rows"]),
                document_count=len(documents),
            )
            return documents, None
        except httpx.HTTPStatusError as exc:
            _log_wfdata_http_error(
                exc,
                candidate=candidate,
                candidate_count=candidate_count,
                attempt=attempt,
                language=language,
                payload=payload,
            )
            return None, exc
        except (httpx.RemoteProtocolError, httpx.ConnectError, httpx.ReadError, httpx.TimeoutException) as exc:
            last_error = exc
            _log_wfdata_connection_error(
                exc,
                candidate=candidate,
                candidate_count=candidate_count,
                attempt=attempt,
                language=language,
                payload=payload,
            )
            if attempt < WFDATA_MAX_ATTEMPTS:
                await asyncio.sleep(WFDATA_RETRY_BACKOFF_SECONDS * attempt)
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            _log_wfdata_parse_error(
                exc,
                candidate=candidate,
                candidate_count=candidate_count,
                attempt=attempt,
                language=language,
                payload=payload,
            )
            return None, exc

    return [], last_error


async def _search_wfdata(query: str, rows: int, *, language: str) -> list[dict[str, Any]]:
    """调用万方文献检索接口，失败返回空列表。"""

    settings = get_settings()
    if not settings.wfdata_api_key:
        logger.info("WFDATA_API_KEY 未配置，跳过万方参考文献检索")
        return []

    payloads = _build_search_payloads(query, rows, language=language)
    headers = _build_wfdata_headers(settings.wfdata_api_key)
    timeout = _build_wfdata_timeout()
    last_error: Exception | None = None

    async with wfdata_slot():
        for candidate, payload in enumerate(payloads, start=1):
            documents, last_error = await _search_wfdata_payload(
                url=settings.wfdata_api_url,
                headers=headers,
                timeout=timeout,
                payload=payload,
                candidate=candidate,
                candidate_count=len(payloads),
                language=language,
                rows=rows,
            )
            if documents is None:
                return []
            if documents or candidate == len(payloads):
                return documents
            logger.info(
                "万方参考文献检索无结果，尝试降级查询: language=%s, old_query=%r, next_query=%r",
                language,
                payload.get("query"),
                payloads[candidate].get("query"),
            )

    last_payload = payloads[-1]
    if last_error:
        logger.warning(
            "万方参考文献检索最终失败: language=%s, rows=%s, query=%r, error_type=%s, error=%s",
            language,
            last_payload.get("rows"),
            last_payload.get("query"),
            type(last_error).__name__,
            last_error,
        )
    else:
        logger.info(
            "万方参考文献检索最终无结果: language=%s, rows=%s, query=%r",
            language,
            last_payload.get("rows"),
            last_payload.get("query"),
        )
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


def _append_formatted_references_with_count(
    lines: list[str],
    items: list[dict[str, Any]],
    target_count: int,
) -> int:
    appended_count = 0
    for item in items:
        if target_count <= 0:
            break
        line = _format_wf_reference(item, len(lines) + 1)
        if not line:
            continue
        lines.append(line)
        target_count -= 1
        appended_count += 1
    return appended_count


def _search_rows_for_target(target_count: int) -> int:
    if target_count <= 0:
        return 0
    return min(target_count + max(2, round(target_count * 0.2)), 100)


async def _search_wfdata_batches(queries: list[str], target_count: int, *, language: str) -> list[dict[str, Any]]:
    """按多组关键词检索万方，返回合并后的候选文献。"""

    if target_count <= 0:
        return []

    rows = _search_rows_for_target(target_count)
    result_buffer = max(rows, target_count * WFDATA_BATCH_BUFFER_MULTIPLIER)
    documents: list[dict[str, Any]] = []

    # 万方接口偶发建连超时，多批查询按顺序试，避免一篇论文瞬间打出十多个连接。
    for query in queries:
        if not query.strip():
            continue
        documents.extend(await _search_wfdata(query, rows, language=language))
        if len(documents) >= result_buffer:
            break
    return documents


def _build_wf_reference_targets(wxnum: int, *, include_english: bool) -> WfReferenceTargets:
    """按是否需要外文文献拆分万方参考文献目标数量。"""

    target_total = max(1, wxnum)
    if include_english:
        target_en = max(3, round(target_total / 3))
        return WfReferenceTargets(total=target_total, zh=target_total - target_en, en=target_en)
    return WfReferenceTargets(total=target_total, zh=target_total, en=0)


async def _search_wf_references(
    zh_queries: list[str],
    en_queries: list[str],
    targets: WfReferenceTargets,
    *,
    include_english: bool,
) -> WfSearchResults:
    """根据中英文检索词调用万方，返回原始文献结果。"""

    search_tasks = [_search_wfdata_batches(zh_queries, targets.zh, language="chi")]
    if include_english and targets.en > 0:
        search_tasks.append(_search_wfdata_batches(en_queries, targets.en, language="eng"))

    grouped_documents = await asyncio.gather(*search_tasks)
    return WfSearchResults(
        zh_documents=grouped_documents[0],
        en_documents=grouped_documents[1] if include_english and len(grouped_documents) > 1 else [],
    )


def _format_wf_references(
    zh_documents: list[dict[str, Any]],
    en_documents: list[dict[str, Any]],
    targets: WfReferenceTargets,
    *,
    include_english: bool,
) -> tuple[str, int, int, int]:
    """去重并格式化万方参考文献，返回文本和数量统计。"""

    seen_titles: set[str] = set()
    zh_items = _dedup_documents(zh_documents, prefer_english=False, seen_titles=seen_titles)
    en_items = _dedup_documents(en_documents, prefer_english=True, seen_titles=seen_titles)

    lines: list[str] = []
    final_zh_count = _append_formatted_references_with_count(lines, zh_items[: targets.zh], targets.zh)
    final_en_count = 0
    if include_english:
        final_en_count = _append_formatted_references_with_count(lines, en_items[: targets.en], targets.en)

    if len(lines) < targets.total:
        final_zh_count += _append_formatted_references_with_count(
            lines,
            zh_items[targets.zh :],
            targets.total - len(lines),
        )
    if include_english and len(lines) < targets.total:
        final_en_count += _append_formatted_references_with_count(
            lines,
            en_items[targets.en :],
            targets.total - len(lines),
        )
    return "\n".join(lines), len(lines), final_zh_count, final_en_count


async def _record_wf_keywords(
    zh_queries: list[str],
    en_queries: list[str],
    targets: WfReferenceTargets,
    *,
    include_english: bool,
) -> None:
    """记录万方关键词提取结果。"""

    await record_process_detail(
        "references",
        "已提取万方文献检索关键词",
        provider="wfapi",
        zh_query=zh_queries[0],
        zh_queries=zh_queries,
        en_queries=en_queries,
        target_total=targets.total,
        target_zh=targets.zh,
        target_en=targets.en,
        en_query_count=len(en_queries) if include_english else 0,
    )


async def _record_wf_search_results(
    search_results: WfSearchResults,
    zh_queries: list[str],
    en_queries: list[str],
    targets: WfReferenceTargets,
    *,
    include_english: bool,
) -> None:
    """记录万方检索结果数量。"""

    await record_process_detail(
        "references",
        "万方文献检索完成",
        provider="wfapi",
        zh_result_count=len(search_results.zh_documents),
        en_result_count=len(search_results.en_documents),
        requested_zh_rows=_search_rows_for_target(targets.zh),
        requested_en_rows=_search_rows_for_target(targets.en),
        zh_query_count=len(zh_queries),
        en_query_count=len(en_queries) if include_english else 0,
    )


async def _record_wf_format_result(
    *,
    final_count: int,
    final_zh_count: int,
    final_en_count: int,
    include_english: bool,
) -> None:
    """记录万方参考文献最终格式化结果。"""

    await record_process_detail(
        "references",
        "参考文献格式化完成",
        provider="wfapi",
        final_count=final_count,
        final_zh_count=final_zh_count,
        final_en_count=final_en_count if include_english else 0,
    )


async def generate_references(
    title: str,
    outline: str,
    wxnum: int = 25,
    include_english: bool = True,
) -> str:
    """使用万方开放平台生成参考文献列表。"""

    targets = _build_wf_reference_targets(wxnum, include_english=include_english)
    zh_queries, en_queries = await _extract_keyword_queries(title, outline)
    await _record_wf_keywords(zh_queries, en_queries, targets, include_english=include_english)

    search_results = await _search_wf_references(
        zh_queries,
        en_queries,
        targets,
        include_english=include_english,
    )
    await _record_wf_search_results(
        search_results,
        zh_queries,
        en_queries,
        targets,
        include_english=include_english,
    )
    if not search_results.zh_documents and not search_results.en_documents:
        logger.warning("万方参考文献检索结果为空")
        return ""

    references, final_count, final_zh_count, final_en_count = _format_wf_references(
        search_results.zh_documents,
        search_results.en_documents,
        targets,
        include_english=include_english,
    )
    await _record_wf_format_result(
        final_count=final_count,
        final_zh_count=final_zh_count,
        final_en_count=final_en_count,
        include_english=include_english,
    )

    return references
