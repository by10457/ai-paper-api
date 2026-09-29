"""大纲公共配置与材料篇幅回归测试。"""

from typing import Any
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from schemas.thesis_material import TaskBookRequest
from services.thesis_material import generation, llm_service


def test_removed_inputs_and_task_budget() -> None:
    payload = {
        "title": "通用研究课题",
        "source_outline": [{"chapter": "绪论", "sections": [{"name": "背景", "abstract": "研究背景"}]}],
        "thesis_config": {"chinese_reference_count": 25, "english_reference_count": 5},
    }
    for field in ("reference_options", "schedule_options"):
        with pytest.raises(ValidationError, match=field):
            TaskBookRequest.model_validate({**payload, field: {}})
    for target in (999, 6001):
        with pytest.raises(ValidationError, match="target_word_count"):
            TaskBookRequest.model_validate({**payload, "target_word_count": target})
    assert TaskBookRequest.model_validate(payload).target_word_count == 2000


@pytest.mark.asyncio
async def test_task_prompt_receives_full_outline_and_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    request = {
        "title": "通用课题",
        "target_word_count": 3000,
        "source_outline": [{"chapter": "绪论", "sections": [
            {"name": "研究背景", "abstract": "保留摘要", "subsections": [{"name": "具体问题"}]},
        ]}],
        "thesis_config": {"aboutmsg": "不编造数据", "chinese_reference_count": 25, "english_reference_count": 5},
    }
    model = AsyncMock(return_value={
        "design_background": "背景",
        "design_goals": ["目标"] * 5,
        "module_tasks": [{"name": "任务", "role": "角色", "responsibilities": "职责", "boundary": "边界"}] * 4,
        "deliverable_forms": ["报告"] * 2,
        "deliverable_requirements": ["成果"] * 2,
        "main_indicators": ["可核验"] * 4,
    })
    monkeypatch.setattr(llm_service, "_ask_json", model)
    await llm_service.generate_task_book_content(request)
    values = model.call_args.args[1]
    assert values["target"] == 3000
    assert "具体问题" in values["context"]
    assert "保留摘要" in values["context"]
    assert "不编造数据" in values["context"]


@pytest.mark.asyncio
async def test_task_budget_repairs_body_and_keeps_plan(monkeypatch: pytest.MonkeyPatch) -> None:
    result: dict[str, Any] = {"design_background": "短文", "schedule_items": [{"start": "第1周"}]}
    repaired = {"design_background": "文" * 2000}
    model = AsyncMock(return_value=repaired)
    monkeypatch.setattr(llm_service, "generate_task_book_content", model)
    await llm_service.repair_length_constraints("task_book", {"title": "通用课题"}, result)
    assert llm_service.task_body_length(result) == 2000
    assert result["schedule_items"] == [{"start": "第1周"}]
    assert "_length_feedback" in model.call_args.args[0]
    metadata = generation._word_count_metadata("task_book", {}, result)
    assert metadata["target"] == metadata["actual"] == 2000
    assert "module_tasks" in metadata["included_fields"]


def test_schedule_uses_relative_weeks() -> None:
    schedule = generation._build_schedule(generation.TASK_BOOK_SCHEDULE, default_weeks=20)
    assert schedule[0]["start"] == "第1周"
    assert schedule[-1]["end"] == "第20周"


@pytest.mark.asyncio
async def test_task_budget_does_not_regenerate_valid_body(monkeypatch: pytest.MonkeyPatch) -> None:
    model = AsyncMock()
    monkeypatch.setattr(llm_service, "generate_task_book_content", model)
    await llm_service.repair_length_constraints("task_book", {}, {"design_background": "文" * 2000})
    model.assert_not_awaited()


def test_task_rejects_out_of_budget_body() -> None:
    with pytest.raises(RuntimeError, match="正文总字数"):
        generation._validate_result("task_book", {"design_background": "短文"}, 0, {"target_word_count": 2000})
