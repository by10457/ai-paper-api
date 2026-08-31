import json
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage

from services.thesis.content import reference_service_wfapi as wf
from services.thesis_material import reference_service as service

TOPIC = "植保无人机在小麦病虫害防治中的应用效果研究"


def english_reference(index=1, title="UAV spraying for wheat pest control", doi="10.1000/test"):
    return service.parse_reference_records(
        f"[{index}]Smith J.{title}[J].Crop Protection,2024,12(2):10-20."
        + (f" doi:{doi}." if doi else ""),
        provider="serpapi",
    )[0]


def test_wanfang_preserves_doi_through_format_and_parse():
    document = {"fields": {
        "Title": {"stringValue": "UAV spraying for wheat pest control"},
        "Creator": {"stringValue": "Smith J"}, "PublishYear": {"numberValue": 2024},
        "PeriodicalTitle": {"stringValue": "Crop Protection"}, "Page": {"stringValue": "10-20"},
        "DOI": {"stringValue": "10.1000/wheat"},
    }}
    item = wf._normalize_wf_document(document, prefer_english=True)
    text = wf._format_wf_reference(item, 1)
    record = service.parse_reference_records(text, provider="wfapi")[0]
    assert record.doi == "10.1000/wheat"
    assert record.pages == "10-20"
    assert record.language == "en"
    assert service._has_delivery_metadata(record)
    item["doi"] = ""
    assert "doi:" not in wf._format_wf_reference(item, 1)


def test_doi_is_not_misread_as_page_number():
    record = service.parse_reference_records(
        "[1]Smith J.UAV spraying for wheat pest control[J].Crop Protection,2024. doi:10.1000/wheat.",
        provider="wfapi",
    )[0]
    assert record.pages == ""
    assert record.doi == "10.1000/wheat"


async def test_unknown_topic_english_is_reviewed_not_automatically_discarded(monkeypatch):
    calls = []
    events = []

    async def review(title, records):
        calls.append((title, [item.title for item in records]))
        return {0}

    async def record_event(stage, message, **details):
        events.append(details)

    monkeypatch.setattr(service, "_review_english_relevance", review)
    monkeypatch.setattr(service, "record_process_detail", record_event)
    relevant = english_reference()
    unrelated = english_reference(2, "Stock market portfolio optimization")
    no_doi = english_reference(3, "Drone application in wheat fields", doi="")
    retracted = english_reference(4, "Retracted: UAV spraying for wheat pest control")
    cache = {}
    assert service._matched_concepts(service._normalized_search_text(TOPIC)) == set()
    result = await service._filter_reference_records(TOPIC, "市场识别", [relevant, unrelated, no_doi, retracted], cache)
    assert result == [relevant]
    assert calls == [(TOPIC, [relevant.title, unrelated.title])]
    assert events[0]["parsed_en"] == 4
    assert events[0]["metadata_valid_en"] == 2
    assert events[0]["missing_doi_en"] == 1
    assert events[0]["accepted_en"] == 1
    assert await service._filter_reference_records(TOPIC, "", [relevant, unrelated], cache) == [relevant]
    assert len(calls) == 1


async def test_semantic_review_failure_does_not_admit_unverified_records(monkeypatch):
    async def review(title, records):
        raise TimeoutError("unavailable")

    monkeypatch.setattr(service, "_review_english_relevance", review)
    cache = {}
    assert await service._filter_reference_records(TOPIC, "", [english_reference()], cache) == []
    assert cache == {}  # A transient failure is not cached as a relevance decision.


@pytest.mark.parametrize("response", [
    '{"keep": [-1]}', '{"keep": [1]}', '{"keep": [true]}',
    '{"keep": ["0"]}', '{"keep": null}', '{}', '[]', 'not json',
])
async def test_semantic_review_rejects_invalid_model_output(monkeypatch, response):
    class LLM:
        async def ainvoke(self, messages):
            return AIMessage(content=response)

    async def create(*args, **kwargs):
        return LLM()

    monkeypatch.setattr(service, "create_configured_llm", create)
    with pytest.raises(ValueError):
        await service._review_english_relevance(TOPIC, [english_reference()])


async def test_semantic_review_only_selects_original_candidates(monkeypatch):
    class LLM:
        async def ainvoke(self, messages):
            payload = json.loads(messages[1].content)
            assert payload["topic"] == TOPIC
            assert payload["candidates"] == [{"index": 0, "title": "UAV spraying for wheat pest control"}]
            return AIMessage(content='```json\n{"keep":[0,0]}\n```')

    async def create(*args, **kwargs):
        return LLM()

    monkeypatch.setattr(service, "create_configured_llm", create)
    assert await service._review_english_relevance(TOPIC, [english_reference()]) == {0}


async def test_retrieval_filters_before_merging_and_keeps_english_quota(monkeypatch):
    chinese = "\n".join(
        f"[{i}]张三.植保无人机小麦病虫害防治试验{i}[J].农业科学,2024,12(2):10-20."
        for i in range(1, 18)
    )
    english = [english_reference(i, f"UAV spraying for wheat pest control trial {i}") for i in range(8)]

    async def primary(*args, **kwargs):
        # Same English titles in the primary source, but unusable metadata.
        return chinese + "\n" + "\n".join(item.formatted.split(" doi:")[0] for item in english)

    async def fallback(*args, **kwargs):
        return "\n".join(item.formatted for item in english)

    async def review(title, records):
        return set(range(len(records)))

    monkeypatch.setattr(service, "get_settings", lambda: SimpleNamespace(reference_provider_mode="wfapi"))
    monkeypatch.setattr(service, "generate_references", primary)
    monkeypatch.setattr(service.reference_service_serpapi, "generate_references", fallback)
    monkeypatch.setattr(service, "_review_english_relevance", review)
    result = await service.retrieve_reference_records(
        TOPIC, "", target_count=25, include_foreign=True,
    )
    assert service._language_counts(result) == (17, 8)
    assert len(result) == 25
    assert [item.index for item in result] == list(range(1, 26))
    assert all(item.doi for item in result if item.language == "en")


async def test_language_supplement_preserves_semantically_approved_english(monkeypatch):
    calls = []

    async def supplement(*args, **kwargs):
        calls.append(kwargs)
        return english_reference().formatted

    async def review(title, records):
        return {0}

    monkeypatch.setattr(service.reference_service_serpapi, "generate_references", supplement)
    monkeypatch.setattr(service, "_review_english_relevance", review)
    result = await service._supplement_language_shortage(TOPIC, "", [], 0, 1, {})
    assert service._language_counts(result) == (0, 1)
    assert len(calls) == 1
    assert calls[0]["include_chinese"] is False


# 配额仅是检索目标，重复补检后仍不足时返回真实的可用数量
@pytest.mark.parametrize("available_count", [0, 3, 26])
async def test_reference_shortage_returns_available_records(
    monkeypatch: pytest.MonkeyPatch, available_count: int,
) -> None:
    """覆盖零文献、总量不足和英文为零，所有外部检索均使用替身。"""
    calls: list[dict[str, object]] = []

    async def search(*args: object, **kwargs: object) -> str:
        calls.append(kwargs)
        return "\n".join(
            f"[{i}]测试作者.植保无人机小麦病虫害防治试验{i}[J].测试期刊,2024,12(2):10-20."
            for i in range(1, available_count + 1)
        )

    monkeypatch.setattr(service, "get_settings", lambda: SimpleNamespace(reference_provider_mode="wfapi"))
    monkeypatch.setattr(service, "generate_references", search)
    monkeypatch.setattr(service.reference_service_wfapi, "generate_references", search)
    monkeypatch.setattr(service.reference_service_serpapi, "generate_references", search)

    records = await service.retrieve_reference_records(TOPIC, "", target_count=25, include_foreign=True)

    assert len(records) == min(available_count, 25)
    assert [item.index for item in records] == list(range(1, len(records) + 1))
    assert len(calls) <= 4  # 首检、备用源及中英文各一次无新增补检后停止。
    quality = service.reference_quality_summary(records, target_count=25, include_foreign=True)
    assert quality["status"] == ("unavailable" if not records else "limited")
    assert quality["actual_count"] == len(records)
    assert quality["warnings"]


# 检索网络故障与数量不足均可降级，但程序错误不能被伪装为质量提示
async def test_reference_network_timeout_is_nonfatal(monkeypatch: pytest.MonkeyPatch) -> None:
    """超时返回零文献；不伪造记录或无限重试。"""
    async def timeout(*args: object, **kwargs: object) -> str:
        raise TimeoutError("test provider timeout")

    monkeypatch.setattr(service, "get_settings", lambda: SimpleNamespace(reference_provider_mode="wfapi"))
    monkeypatch.setattr(service, "generate_references", timeout)
    monkeypatch.setattr(service.reference_service_wfapi, "generate_references", timeout)
    monkeypatch.setattr(service.reference_service_serpapi, "generate_references", timeout)

    assert await service.retrieve_reference_records(TOPIC, "", target_count=25, include_foreign=True) == []


# 总预算到期时保留已经通过验证的首批文献
async def test_reference_deadline_preserves_validated_batch(monkeypatch: pytest.MonkeyPatch) -> None:
    """用事件阻塞备用源，不使用 sleep 或真实服务来触发总超时。"""
    import asyncio

    async def primary(*args: object, **kwargs: object) -> str:
        return "[1]测试作者.植保无人机小麦病虫害防治试验[J].测试期刊,2024,12(2):10-20."

    async def fallback(*args: object, **kwargs: object) -> str:
        await asyncio.Event().wait()
        return ""

    monkeypatch.setattr(service, "get_settings", lambda: SimpleNamespace(reference_provider_mode="wfapi"))
    monkeypatch.setattr(service, "generate_references", primary)
    monkeypatch.setattr(service.reference_service_serpapi, "generate_references", fallback)
    monkeypatch.setattr(service, "REFERENCE_TOTAL_TIMEOUT_SECONDS", 0)
    records = await service.retrieve_reference_records(TOPIC, "", target_count=25, include_foreign=True)
    assert len(records) == 1


# 真正的内部错误仍应向上抛出，避免隐藏代码缺陷
async def test_reference_programming_error_is_not_swallowed(monkeypatch: pytest.MonkeyPatch) -> None:
    """数量降级不等于捕获所有异常。"""
    async def broken(*args: object, **kwargs: object) -> str:
        raise RuntimeError("test internal error")

    monkeypatch.setattr(service, "generate_references", broken)
    with pytest.raises(RuntimeError, match="test internal error"):
        await service.retrieve_reference_records(TOPIC, "", target_count=25, include_foreign=True)


# 中文不足时也允许用合格外文继续生成，不强制中文比例
async def test_reference_chinese_shortage_keeps_available_english(monkeypatch: pytest.MonkeyPatch) -> None:
    """实际五篇外文低于六篇目标时，返回五篇并产生数量与语言提示。"""
    from unittest.mock import AsyncMock

    batch = "\n".join(english_reference(i, f"UAV spraying for wheat pest control {i}").formatted for i in range(1, 6))
    search = AsyncMock(return_value=batch)
    monkeypatch.setattr(service, "get_settings", lambda: SimpleNamespace(reference_provider_mode="wfapi"))
    monkeypatch.setattr(service, "generate_references", search)
    monkeypatch.setattr(service.reference_service_wfapi, "generate_references", search)
    monkeypatch.setattr(service.reference_service_serpapi, "generate_references", search)
    monkeypatch.setattr(service, "_review_english_relevance", AsyncMock(return_value=set(range(5))))
    records = await service.retrieve_reference_records(TOPIC, "", target_count=6, include_foreign=True)
    assert service._language_counts(records) == (0, 5)
    quality = service.reference_quality_summary(records, target_count=6, include_foreign=True)
    assert {item["code"] for item in quality["warnings"]} == {
        "reference_count_shortfall", "reference_language_shortfall",
    }


# 不需要外文时不得为了默认中英文比例额外检索
async def test_reference_chinese_only_target_does_not_trigger_foreign_search(monkeypatch: pytest.MonkeyPatch) -> None:
    """中文已足量时仅首检一次，不生成语言不足提示。"""
    from unittest.mock import AsyncMock

    primary = AsyncMock(return_value="[1]测试作者.植保无人机小麦病虫害防治试验[J].测试期刊,2024,12(2):10-20.")
    fallback = AsyncMock(side_effect=AssertionError("不得额外访问供应商"))
    monkeypatch.setattr(service, "get_settings", lambda: SimpleNamespace(reference_provider_mode="wfapi"))
    monkeypatch.setattr(service, "generate_references", primary)
    monkeypatch.setattr(service.reference_service_wfapi, "generate_references", fallback)
    monkeypatch.setattr(service.reference_service_serpapi, "generate_references", fallback)
    records = await service.retrieve_reference_records(TOPIC, "", target_count=1, include_foreign=False)
    assert service.reference_quality_summary(records, target_count=1, include_foreign=False)["warnings"] == []
    primary.assert_awaited_once_with(TOPIC, "", wxnum=1, include_english=False)
