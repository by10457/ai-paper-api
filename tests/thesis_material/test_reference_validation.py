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
        TOPIC, "", target_count=25, minimum_count=25, minimum_chinese_count=17, minimum_english_count=8,
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
