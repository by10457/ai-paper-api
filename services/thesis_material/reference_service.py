"""把现有真实文献检索结果转换为通用结构化记录。"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from html import unescape
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
_PAGES = re.compile(r"(?P<pages>[A-Za-z]?\d{1,8}(?:[-–][A-Za-z]?\d{1,8})?(?:\+\d+)?)")
_DOI = re.compile(r"(?:doi\s*[:：]?\s*|https?://doi\.org/)(10\.\d{4,9}/[-._;()/:A-Z0-9]+)", re.IGNORECASE)
_URL = re.compile(r"https?://[^\s，。]+", re.IGNORECASE)

_TECHNOLOGY_TERMS = (
    "springboot",
    "spring",
    "vue",
    "java",
    "mysql",
    "redis",
    "python",
    "django",
    "fastapi",
    "react",
    "深度学习",
    "机器学习",
    "神经网络",
    "推荐系统",
)
_GENERIC_TERMS = (
    "基于",
    "研究",
    "设计",
    "实现",
    "系统",
    "平台",
    "技术",
    "应用",
    "分析",
    "development",
    "design",
    "implementation",
    "system",
    "platform",
    "application",
    "study",
)
_BUSINESS_CONCEPT_GROUPS = (
    ("校园", "高校", "大学生", "campus", "college", "university", "student"),
    ("二手", "闲置", "旧物", "转售", "secondhand", "second-hand", "resale", "preowned", "usedgoods"),
    ("交易", "买卖", "市场", "交换", "trading", "trade", "marketplace", "exchange"),
    ("教育", "教学", "课堂", "education", "teaching", "learning"),
    ("物流", "供应链", "配送", "logistics", "supplychain", "delivery"),
    ("医疗", "健康", "疾病", "medical", "health", "disease"),
    ("农业", "农产品", "乡村", "agriculture", "agricultural", "rural"),
    ("图像", "视觉", "识别", "image", "vision", "recognition"),
    ("电商", "电子商务", "购物", "ecommerce", "e-commerce", "shopping"),
    ("预约", "预订", "booking", "reservation"),
)


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
        for attempt in range(2):
            chinese_count, english_count = _language_counts(records)
            needed = (
                target_chinese_count - chinese_count
                if language == "zh"
                else target_english_count - english_count
            )
            if needed <= 0:
                break
            # 检索结果常与首轮重复；逐轮扩大批量，并在计数前先执行同一相关性门槛。
            request_count = min(max(needed * 3, 10) * (attempt + 1), 30)
            supplement = await generator(request_count)
            usable = _rank_records_by_relevance(
                title,
                context,
                parse_reference_records(supplement, provider=f"language_{language}"),
            )
            records = _merge_records(records, usable)

    target_total = target_chinese_count + target_english_count
    if len(records) < target_total:
        request_count = min(max(target_total * 2, 12), 30)
        for language, generator in (
            ("zh", lambda count: reference_service_wfapi.generate_references(
                title, context, wxnum=count, include_english=False)),
            ("en", lambda count: reference_service_serpapi.generate_references(
                title, context, wxnum=count, include_english=True, include_chinese=False)),
        ):
            supplement = await generator(request_count)
            usable = _rank_records_by_relevance(
                title,
                context,
                parse_reference_records(supplement, provider=f"total_{language}"),
            )
            records = _merge_records(records, usable)
            if len(records) >= target_total:
                break
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
    """以业务主题为准入门槛，技术主题只作为次级加分项。"""

    query = _normalized_search_text(f"{title}{context}")
    topic_query = _normalized_search_text(title)
    query_business = _strip_terms(topic_query, (*_TECHNOLOGY_TERMS, *_GENERIC_TERMS))
    # The outline contains supporting concepts such as markets, identification,
    # and information systems. They may affect ranking, but must not redefine
    # the paper's core topic or become mandatory relevance gates.
    query_concepts = _matched_concepts(topic_query)
    ranked: list[tuple[int, ReferenceRecord]] = []
    for item in records:
        if "retracted" in item.title.lower() or "撤稿" in item.title:
            continue
        if not _has_delivery_metadata(item):
            continue
        score = _relevance_score(query, query_business, query_concepts, item)
        if score is not None:
            ranked.append((score, item))
    ranked.sort(key=lambda pair: (pair[0], -len(pair[1].title)), reverse=True)
    return [item for _, item in ranked]


def _relevance_score(
    query: str,
    query_business: str,
    query_concepts: set[int],
    item: ReferenceRecord,
) -> int | None:
    candidate = _normalized_search_text(item.title)
    candidate_business = _strip_terms(candidate, (*_TECHNOLOGY_TERMS, *_GENERIC_TERMS))
    matched_concepts = query_concepts & _matched_concepts(candidate)
    overlap = len(_text_bigrams(query_business) & _text_bigrams(candidate_business))
    denominator = max(1, min(len(_text_bigrams(query_business)), len(_text_bigrams(candidate_business))))
    overlap_ratio = overlap / denominator
    required_concepts = 2 if len(query_concepts) >= 2 else len(query_concepts)
    concept_match = required_concepts > 0 and len(matched_concepts) >= required_concepts
    direct_business_match = (
        len(query_concepts) < 2
        and item.language == "zh"
        and overlap >= 2
        and overlap_ratio >= 0.08
    )
    if not concept_match and not direct_business_match:
        return None
    technology_overlap = sum(1 for term in _TECHNOLOGY_TERMS if term in query and term in candidate)
    return len(matched_concepts) * 20 + round(overlap_ratio * 20) + overlap + technology_overlap * 3


def _matched_concepts(value: str) -> set[int]:
    return {
        index
        for index, terms in enumerate(_BUSINESS_CONCEPT_GROUPS)
        if any(_normalized_search_text(term) in value for term in terms)
    }


def _strip_terms(value: str, terms: tuple[str, ...]) -> str:
    result = value
    for term in terms:
        result = result.replace(_normalized_search_text(term), "")
    return result


def _has_delivery_metadata(item: ReferenceRecord) -> bool:
    """过滤无法形成完整交付著录信息的记录。"""

    if not item.title or not item.authors or not item.year or not item.source:
        return False
    if item.document_type.upper() == "J" and not (item.pages or item.doi):
        return False
    if item.language == "en" and not item.doi:
        return False
    return True


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
        line = re.sub(r"\bet al\.\.", "et al.", unescape(raw_line.strip()), flags=re.IGNORECASE)
        match = _REFERENCE_LINE.match(line)
        if match is None:
            continue
        body = match.group("body").strip()
        marker_match = _TYPE_MARKER.search(body)
        if marker_match is None:
            continue
        heading = marker_match.group("title").strip(" .,，")
        if "." in heading:
            author_text, title = heading.split(".", 1)
        else:
            author_text, title = "", heading
        title = title.strip(" .,，")
        if re.search(r"(?:…|\.{3})", title):
            continue
        title_key = re.sub(r"\s+", "", title).lower()
        if not title_key or title_key in seen_titles:
            continue
        seen_titles.add(title_key)

        authors = [item.strip() for item in re.split(r"[,，]", author_text) if item.strip()]
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
