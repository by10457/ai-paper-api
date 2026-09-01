import asyncio

import pytest

from services.thesis.content import reference_query, reference_service_wfapi


def _wf_text_values(*values: str) -> dict:
    return {"listValue": {"values": [{"stringValue": value} for value in values]}}


def _wf_document(zh_title: str, en_title: str, year: int, cited_count: int) -> dict:
    return {
        "resourceType": "Periodical",
        "fields": {
            "Title": _wf_text_values(zh_title, en_title),
            "Creator": _wf_text_values("张三", "李四"),
            "PublishYear": {"numberValue": year},
            "PeriodicalTitle": _wf_text_values("软件学报", "Journal of Software"),
            "Volum": {"stringValue": "10"},
            "Issue": {"stringValue": "2"},
            "Page": {"stringValue": "11-18"},
            "CitedCount": {"numberValue": cited_count},
            "Type": {"stringValue": "Periodical"},
        },
    }


def test_wfapi_splits_25_references_into_17_chinese_and_8_english(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, int, str]] = []

    async def fake_extract_keyword_queries(title: str, outline: str) -> tuple[list[str], list[str]]:
        return ["中文关键词", "中文关联关键词"], ["english keyword", "paper generation"]

    async def fake_search_wfdata(query: str, rows: int, *, language: str) -> list[dict]:
        calls.append((query, rows, language))
        if language == "chi":
            return [_wf_document(f"中文文献{i}", f"Chinese Reference {i}", 2020 + i, 100 - i) for i in range(1, 21)]
        return [_wf_document(f"英文中文题名{i}", f"English Reference {i}", 2020 + i, 100 - i) for i in range(1, 11)]

    monkeypatch.setattr(reference_service_wfapi, "_extract_keyword_queries", fake_extract_keyword_queries)
    monkeypatch.setattr(reference_service_wfapi, "_search_wfdata", fake_search_wfdata)

    references = asyncio.run(reference_service_wfapi.generate_references("题目", "大纲", wxnum=25, include_english=True))
    lines = references.splitlines()

    assert len(lines) == 25
    assert sum("中文文献" in line for line in lines) == 17
    assert sum("English Reference" in line for line in lines) == 8
    assert set(calls) == {
        ("中文关键词", 20, "chi"),
        ("中文关联关键词", 20, "chi"),
        ("english keyword", 10, "eng"),
        ("paper generation", 10, "eng"),
    }


def test_wfapi_returns_chinese_only_when_english_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, int, str]] = []

    async def fake_extract_keyword_queries(title: str, outline: str) -> tuple[list[str], list[str]]:
        return ["中文关键词", "中文延伸关键词"], ["english keyword"]

    async def fake_search_wfdata(query: str, rows: int, *, language: str) -> list[dict]:
        calls.append((query, rows, language))
        return [_wf_document(f"中文文献{i}", f"Chinese Reference {i}", 2020 + i, 100 - i) for i in range(1, 8)]

    monkeypatch.setattr(reference_service_wfapi, "_extract_keyword_queries", fake_extract_keyword_queries)
    monkeypatch.setattr(reference_service_wfapi, "_search_wfdata", fake_search_wfdata)

    references = asyncio.run(reference_service_wfapi.generate_references("题目", "大纲", wxnum=5, include_english=False))
    lines = references.splitlines()

    assert len(lines) == 5
    assert all("中文文献" in line for line in lines)
    assert set(calls) == {
        ("中文关键词", 7, "chi"),
        ("中文延伸关键词", 7, "chi"),
    }


def test_wfapi_fills_total_count_with_chinese_when_english_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_extract_keyword_queries(title: str, outline: str) -> tuple[list[str], list[str]]:
        return ["中文关键词", "中文关联关键词"], ["english keyword"]

    async def fake_search_wfdata_batches(queries: list[str], target_count: int, *, language: str) -> list[dict]:
        if language == "eng":
            return []
        return [_wf_document(f"中文文献{i}", f"Chinese Reference {i}", 2020 + i, 100 - i) for i in range(1, 31)]

    monkeypatch.setattr(reference_service_wfapi, "_extract_keyword_queries", fake_extract_keyword_queries)
    monkeypatch.setattr(reference_service_wfapi, "_search_wfdata_batches", fake_search_wfdata_batches)

    references = asyncio.run(reference_service_wfapi.generate_references("题目", "大纲", wxnum=25, include_english=True))
    lines = references.splitlines()

    assert len(lines) == 25
    assert all("中文文献" in line for line in lines)


def test_wfapi_search_payload_filters_language() -> None:
    zh_payload = reference_service_wfapi._build_search_payload("深度学习 图像识别", 200, language="chi")
    en_payload = reference_service_wfapi._build_search_payload("deep learning", 10, language="eng")

    assert zh_payload["query"] == "(深度学习 AND 图像识别) AND Language:chi"
    assert zh_payload["rows"] == 100
    assert en_payload["query"] == "(deep AND learning) AND Language:eng"
    assert en_payload["rows"] == 10


def test_wfapi_collects_keyword_batches() -> None:
    keyword_data = {
        "zh": "校园一卡通",
        "zh_related": ["校园管理系统", "数字校园"],
        "zh_extended": ["高校信息化", "智慧校园"],
        "en": ["campus card system"],
        "en_related": ["smart campus"],
        "en_extended": ["university information system"],
    }

    zh_queries = reference_query.collect_keyword_queries(
        keyword_data,
        ("zh", "zh_related", "zh_extended"),
        fallback="题目",
        limit=8,
    )
    en_queries = reference_query.collect_keyword_queries(
        keyword_data,
        ("en", "en_related", "en_extended"),
        fallback="title",
        limit=6,
    )

    assert zh_queries == ["校园一卡通", "校园管理系统", "数字校园", "高校信息化", "智慧校园"]
    assert en_queries == ["campus card system", "smart campus", "university information system"]


def test_reference_keyword_parsers_accept_fenced_json_with_explanation() -> None:
    """关键词模型偶发包裹代码围栏时不应退化成中文标题检索英文文献。"""

    raw = '关键词如下：\n```json\n{"zh":"校园二手交易","en":["campus resale platform"]}\n```'

    assert reference_query.parse_keyword_json(raw)["en"] == ["campus resale platform"]
    assert reference_query.parse_keyword_json(raw)["zh"] == "校园二手交易"


def test_wfapi_builds_less_restrictive_english_fallback_query() -> None:
    """英文多词 AND 查询为零时应保留主题词并减少无效限定词。"""

    payloads = reference_service_wfapi._build_search_payloads(
        "generative artificial intelligence ideological political education",
        10,
        language="eng",
    )

    assert [payload["query"] for payload in payloads] == [
        "(generative AND artificial AND intelligence AND ideological AND political AND education) AND Language:eng",
        "(generative AND artificial AND intelligence AND education) AND Language:eng",
    ]


def test_english_query_normalization_uses_dynamic_subject_queries() -> None:
    """英文查询应来自模型规划的研究对象，不应由具体中文题目触发硬编码短语。"""

    queries = reference_query.normalize_english_queries(
        [
            "Spring Boot Vue web development",
            "campus second-hand marketplace",
            "university resale behavior",
        ],
        title="基于Spring Boot与Vue的校园二手交易平台设计与实现",
        limit=3,
    )

    assert queries == ["campus second-hand marketplace", "university resale behavior"]


def test_chinese_title_without_model_translation_does_not_query_english_database() -> None:
    """中文题目的英文规划失败时宁可报告外文不足，也不能用中文或技术栈冒充英文主题。"""

    assert (
        reference_query.normalize_english_queries(
            [],
            title="基于Spring Boot与Vue的校园二手交易平台设计与实现",
            limit=3,
        )
        == []
    )


def test_english_title_can_be_used_as_language_fallback() -> None:
    """英文题目本身具备研究主题时可以作为通用降级查询。"""

    assert reference_query.normalize_english_queries(
        [],
        title="Vision transformer for medical image classification",
        limit=3,
    ) == ["Vision transformer for medical image classification"]
