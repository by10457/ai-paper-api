import asyncio

from services.thesis.content import reference_service_wfapi


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


def test_wfapi_splits_25_references_into_17_chinese_and_8_english(monkeypatch) -> None:
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


def test_wfapi_returns_chinese_only_when_english_disabled(monkeypatch) -> None:
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


def test_wfapi_fills_total_count_with_chinese_when_english_empty(monkeypatch) -> None:
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

    zh_queries = reference_service_wfapi._collect_keyword_queries(
        keyword_data,
        ("zh", "zh_related", "zh_extended"),
        "题目",
        8,
    )
    en_queries = reference_service_wfapi._collect_keyword_queries(
        keyword_data,
        ("en", "en_related", "en_extended"),
        "title",
        6,
    )

    assert zh_queries == ["校园一卡通", "校园管理系统", "数字校园", "高校信息化", "智慧校园"]
    assert en_queries == ["campus card system", "smart campus", "university information system"]
