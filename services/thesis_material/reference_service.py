"""把现有真实文献检索结果转换为通用结构化记录。"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from math import ceil

from core.config import get_settings
from schemas.thesis_material import ReferenceRecord
from services.thesis.content import reference_service_serpapi, reference_service_wfapi
from services.thesis.content.reference_service import (
    REFERENCE_MODE_MIXED,
    REFERENCE_MODE_SERPAPI,
    REFERENCE_MODE_WFAPI,
    generate_references,
)

_REFERENCE_LINE = re.compile(r"^\[(?P<index>\d+)\]\s*(?P<body>.+)$")
_TYPE_MARKER = re.compile(r"(?P<title>.+?)\[(?P<marker>[A-Z])\]")
_YEAR = re.compile(r"(?<!\d)((?:19|20)\d{2})(?!\d)")
_VOLUME_ISSUE = re.compile(r"(?P<volume>\d+)\s*[（(](?P<issue>\d+)[)）]")
_PAGES = re.compile(r"(?P<pages>\d{1,5}(?:[-–]\d{1,5})?(?:\+\d+)?)")
_DOI = re.compile(r"(?:doi\s*[:：]?\s*|https?://doi\.org/)(10\.\d{4,9}/[-._;()/:A-Z0-9]+)", re.IGNORECASE)
_URL = re.compile(r"https?://[^\s，。]+", re.IGNORECASE)


class ReferenceShortageError(RuntimeError):
    """真实文献数量低于产品交付下限。"""


async def retrieve_reference_records(
    title: str,
    context: str,
    *,
    target_count: int,
    minimum_count: int,
    minimum_chinese_count: int,
    minimum_english_count: int,
) -> list[ReferenceRecord]:
    """调用真实检索链，并执行中英文文献的目标和最低配额校验。"""

    settings = get_settings()
    primary_provider = settings.reference_provider_mode.strip().lower()
    text = await generate_references(
        title,
        context,
        wxnum=target_count,
        include_english=True,
    )
    records = parse_reference_records(text, provider=primary_provider)
    for provider, generator in _fallback_generators(primary_provider):
        if _meets_quota(records, target_count, *_target_language_quota(target_count)):
            break
        supplement = await generator(
            title,
            context,
            wxnum=max(target_count - len(records), minimum_count),
            include_english=True,
        )
        records = _merge_records(records, parse_reference_records(supplement, provider=provider))

    records = _rank_records_by_relevance(title, context, records)

    if minimum_english_count == 0:
        target_chinese_count, target_english_count = target_count, 0
    else:
        target_chinese_count, target_english_count = _target_language_quota(target_count)
    records = await _supplement_language_shortage(
        title,
        context,
        records,
        target_chinese_count,
        target_english_count,
    )
    records = _rank_records_by_relevance(title, context, records)
    if _meets_quota(records, target_count, target_chinese_count, target_english_count):
        return _select_records(records, target_count, target_chinese_count, target_english_count)
    if _meets_quota(records, minimum_count, minimum_chinese_count, minimum_english_count):
        return _select_records(records, minimum_count, minimum_chinese_count, minimum_english_count)
    chinese_count, english_count = _language_counts(records)
    raise ReferenceShortageError(
        "真实参考文献不足："
        f"共{len(records)}篇（中文{chinese_count}篇、英文{english_count}篇），"
        f"最低需要{minimum_count}篇（中文{minimum_chinese_count}篇、英文{minimum_english_count}篇）"
    )


def _fallback_generators(
    primary_provider: str,
) -> list[tuple[str, Callable[..., Awaitable[str]]]]:
    if primary_provider == REFERENCE_MODE_WFAPI:
        return [(REFERENCE_MODE_SERPAPI, reference_service_serpapi.generate_references)]
    if primary_provider == REFERENCE_MODE_SERPAPI:
        return [(REFERENCE_MODE_WFAPI, reference_service_wfapi.generate_references)]
    if primary_provider == REFERENCE_MODE_MIXED:
        return [
            (REFERENCE_MODE_WFAPI, reference_service_wfapi.generate_references),
            (REFERENCE_MODE_SERPAPI, reference_service_serpapi.generate_references),
        ]
    return [(REFERENCE_MODE_SERPAPI, reference_service_serpapi.generate_references)]


def _merge_records(
    existing: list[ReferenceRecord],
    supplement: list[ReferenceRecord],
    target_count: int | None = None,
) -> list[ReferenceRecord]:
    merged: list[ReferenceRecord] = []
    seen_titles: set[str] = set()
    for item in [*existing, *supplement]:
        title_key = re.sub(r"\s+", "", item.title).lower()
        if not title_key or title_key in seen_titles:
            continue
        seen_titles.add(title_key)
        index = len(merged) + 1
        formatted = re.sub(r"^\[\d+\]", f"[{index}]", item.formatted, count=1)
        merged.append(item.model_copy(update={"index": index, "formatted": formatted}))
        if target_count is not None and len(merged) >= target_count:
            break
    return merged


def _target_language_quota(target_count: int) -> tuple[int, int]:
    """按已确认的中文约三分之二、英文约三分之一计算目标配额。"""

    chinese_count = ceil(target_count * 2 / 3)
    return chinese_count, target_count - chinese_count


def _language_counts(records: list[ReferenceRecord]) -> tuple[int, int]:
    return (
        sum(item.language == "zh" for item in records),
        sum(item.language == "en" for item in records),
    )


def _meets_quota(
    records: list[ReferenceRecord],
    total_count: int,
    chinese_count: int,
    english_count: int,
) -> bool:
    actual_chinese_count, actual_english_count = _language_counts(records)
    return (
        len(records) >= total_count
        and actual_chinese_count >= chinese_count
        and actual_english_count >= english_count
    )


async def _supplement_language_shortage(
    title: str,
    context: str,
    records: list[ReferenceRecord],
    target_chinese_count: int,
    target_english_count: int,
) -> list[ReferenceRecord]:
    """按缺口分别检索，避免总数充足却某种语言不足。"""

    for language, generator in (
        ("zh", lambda count: reference_service_wfapi.generate_references(
            title, context, wxnum=count, include_english=False)),
        ("en", lambda count: reference_service_serpapi.generate_references(
            title, context, wxnum=count, include_english=True, include_chinese=False)),
    ):
        chinese_count, english_count = _language_counts(records)
        needed = (target_chinese_count - chinese_count) if language == "zh" else (target_english_count - english_count)
        if needed <= 0:
            continue
        supplement = await generator(max(needed, 2))
        records = _merge_records(
            records,
            parse_reference_records(supplement, provider=f"language_{language}"),
        )
    return records


def _select_records(
    records: list[ReferenceRecord],
    count: int,
    chinese_count: int,
    english_count: int,
) -> list[ReferenceRecord]:
    """优先选足语言配额，再按原检索顺序补足总数并连续编号。"""

    selected = [item for item in records if item.language == "zh"][:chinese_count]
    selected.extend(item for item in records if item.language == "en")
    selected = selected[: chinese_count + english_count]
    selected_titles = {item.title for item in selected}
    selected.extend(item for item in records if item.title not in selected_titles)
    normalized: list[ReferenceRecord] = []
    for index, item in enumerate(selected[:count], start=1):
        formatted = re.sub(r"^\[\d+\]", f"[{index}]", item.formatted, count=1)
        normalized.append(item.model_copy(update={"index": index, "formatted": formatted}))
    return normalized


def _rank_records_by_relevance(
    title: str,
    context: str,
    records: list[ReferenceRecord],
) -> list[ReferenceRecord]:
    """按题名与请求上下文的字符片段重排检索结果，并剔除撤稿记录。"""

    query = _normalized_search_text(f"{title}{context}")
    query_bigrams = _text_bigrams(query)

    def relevance(item: ReferenceRecord) -> tuple[int, int]:
        candidate = _normalized_search_text(item.title)
        overlap = len(query_bigrams & _text_bigrams(candidate))
        direct_bonus = sum(1 for token in ("实验室", "预约", "高校", "教育", "人工智能") if token in query and token in candidate)
        return overlap + direct_bonus * 3, -len(candidate)

    usable = [item for item in records if "retracted" not in item.title.lower() and "撤稿" not in item.title]
    return sorted(usable, key=relevance, reverse=True)


def _normalized_search_text(value: str) -> str:
    """保留中英文数字并统一小写，供轻量相关性排序使用。"""

    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", value.lower())


def _text_bigrams(value: str) -> set[str]:
    """返回字符二元片段，兼容中文与未分词英文题名。"""

    return {value[index : index + 2] for index in range(max(len(value) - 1, 0))}


def parse_reference_records(text: str, *, provider: str) -> list[ReferenceRecord]:
    """解析现有 GB/T 7714 文本，保留可验证的结构化字段。"""

    records: list[ReferenceRecord] = []
    seen_titles: set[str] = set()
    for raw_line in text.splitlines():
        line = raw_line.strip()
        match = _REFERENCE_LINE.match(line)
        if match is None:
            continue
        body = match.group("body").strip()
        marker_match = _TYPE_MARKER.search(body)
        if marker_match is None:
            continue
        title = marker_match.group("title").split(".")[-1].strip(" .,，")
        title_key = re.sub(r"\s+", "", title).lower()
        if not title_key or title_key in seen_titles:
            continue
        seen_titles.add(title_key)

        prefix = body[: marker_match.start()].strip(" .,，")
        authors = [item.strip() for item in re.split(r"[,，]", prefix) if item.strip()]
        suffix = body[marker_match.end() :].strip(" .,，")
        doi_match = _DOI.search(body)
        url_match = _URL.search(body)
        year_match = _YEAR.search(suffix)
        volume_match = _VOLUME_ISSUE.search(suffix)
        pages = ""
        if ":" in suffix:
            pages_match = _PAGES.search(suffix.rsplit(":", 1)[-1])
            pages = pages_match.group("pages").replace("–", "-") if pages_match else ""
        source = suffix.split(",", 1)[0].strip(" .,，") if suffix else ""
        index = len(records) + 1
        records.append(
            ReferenceRecord(
                index=index,
                title=title,
                authors=authors,
                year=year_match.group(1) if year_match else "",
                document_type=marker_match.group("marker"),
                source=source,
                volume=volume_match.group("volume") if volume_match else "",
                issue=volume_match.group("issue") if volume_match else "",
                pages=pages,
                doi=doi_match.group(1).rstrip(".") if doi_match else "",
                language="zh" if any("\u4e00" <= char <= "\u9fff" for char in title) else "en",
                provider=provider,
                source_url=url_match.group(0).rstrip(".") if url_match else "",
                formatted=f"[{index}]{body}",
            )
        )
    return records


__all__ = ["ReferenceShortageError", "parse_reference_records", "retrieve_reference_records"]
