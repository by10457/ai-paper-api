"""真实回归发现的材料交付质量问题。"""

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest
from docx import Document
from docx.oxml.ns import qn

from schemas.thesis_material import ReferenceRecord
from services.thesis.content.reference_service_serpapi import _resolve_doc_marker
from services.thesis_material import llm_service
from services.thesis_material.document_builder import _schedule_text, build_thesis_material_document
from services.thesis_material.llm_service import _clean_task_instructions, normalize_citation_claims


# 单个字段预算与总正文验收分离，避免局部短几十字中断整份文档。
async def test_short_field_uses_final_validation_floor(monkeypatch: pytest.MonkeyPatch) -> None:
    """117 字的有效短字段交由后续总字数校验，而非局部抛错。"""
    monkeypatch.setattr(llm_service, "_ask_text", AsyncMock(return_value="甲" * 116 + "。"))
    text = await llm_service._repair_length_value("feasibility_and_innovation", "甲" * 117, 155, 195, {"title": "测试"}, {})
    assert len(text) == 117


# 局部预算略超不能让已合格的整篇材料失败。
async def test_soft_field_budget_preserves_valid_total(monkeypatch: pytest.MonkeyPatch) -> None:
    """覆盖真实综述 210 字趋势区块，不应触发额外模型调用。"""
    request = {"title": "测试课题", "target_word_count": 3500}
    plan = llm_service.build_length_plan("literature_review", request)
    assert plan.theme is not None
    result: dict[str, Any] = {key: "文" * value.target for key, value in plan.fields.items()}
    result["future_trends"] = "文" * 210
    result["themes"] = [{"content": "文" * plan.theme.target} for _ in range(plan.theme_count)]
    model = AsyncMock(side_effect=AssertionError("合格总篇幅不应整篇重写"))
    monkeypatch.setattr(llm_service, "_ask_text", model)
    await llm_service.repair_length_constraints("literature_review", request, result)
    model.assert_not_awaited()


# 任务书差额只修复正文区块，保留结构、进度及参考文献。
async def test_task_shortfall_repairs_only_background(monkeypatch: pytest.MonkeyPatch) -> None:
    """1710 字样本通过补写背景达到目标，不重新生成全部字段。"""
    result: dict[str, Any] = {"design_background": "文" * 300, "design_goals": ["文" * 1410], "references": ["来源"]}
    model = AsyncMock(return_value="文" * 590)
    monkeypatch.setattr(llm_service, "_ask_text", model)
    monkeypatch.setattr(llm_service, "generate_task_book_content", AsyncMock(side_effect=AssertionError("禁止整篇重写")))
    await llm_service.repair_length_constraints("task_book", {"title": "测试课题"}, result)
    assert llm_service.task_body_length(result) == 2000
    assert result["design_goals"] == ["文" * 1410]
    assert result["references"] == ["来源"]


# 引用安全处理是字数计算的一部分。
async def test_length_repair_counts_normalized_citation_text(monkeypatch: pytest.MonkeyPatch) -> None:
    """模型短句经引用规范化扩写后必须重新计量并修复。"""
    safe_text = "相关主题仍需进一步核对原文，" * 8 + "请确认。"
    rewrite = AsyncMock(side_effect=["文献[1]证明效率提高。", safe_text])
    monkeypatch.setattr(llm_service, "_ask_text", rewrite)
    result = {"references": [{"index": 1, "title": "长题名" * 80}]}
    value = await llm_service._repair_length_value("future_trends", "短句。", 80, 150, {"title": "测试"}, result)
    assert value == safe_text
    assert rewrite.await_count == 2


# 内部占位规则不是用户任务，业务隐私保护要求仍须保留。
def test_task_internal_instructions_are_removed_without_losing_business_privacy() -> None:
    """剔除模型误抄的指令并保留合法任务内容。"""
    assert _clean_task_instructions([
        "不得填写或推断姓名、学号，相关字段由文档层固定占位。",
        "保护交易用户个人信息。",
        {"boundary": "限于校园交易；不复制论文目录作为任务书内容。"},
    ]) == ["保护交易用户个人信息。", {"boundary": "限于校园交易；"}]


# 用户已确认的文献数量不是模型擅自建议的性能指标。
def test_confirmed_reference_counts_are_not_generated_metrics() -> None:
    """只豁免完全匹配配置的数量，不豁免同句新增性能阈值。"""
    result: dict[str, Any] = {"deliverable_requirements": ["中文文献不少于8篇，英文文献不少于2篇。", "响应低于100毫秒。"]}
    llm_service._mark_unconfirmed_generated_metrics(
        {"thesis_config": {"chinese_reference_count": 8, "english_reference_count": 2}}, result,
    )
    assert not result["deliverable_requirements"][0].startswith("建议值")
    assert result["deliverable_requirements"][1].startswith("建议值")


# 引用降级不能复制任意长题名而破坏正文预算。
def test_unsupported_claim_repair_does_not_expand_titles() -> None:
    """保留可定位编号，显式提示证据不足，长度不受题名长度影响。"""
    result: dict[str, Any] = {"conclusion": "文献[1]证明效果改善。", "references": [{"index": 1, "title": "长题名" * 100}]}
    normalize_citation_claims(result)
    assert "[1]" in result["conclusion"]
    assert "改善" not in result["conclusion"]
    assert len(result["conclusion"]) < 60


# 来源类型不能被非空会议/图书容器名称覆盖。
@pytest.mark.parametrize(("source_type", "expected"), [("proceedings-article", "C"), ("book-chapter", "M"), ("journal-article", "J")])
def test_explicit_reference_type_precedes_container(source_type: str, expected: str) -> None:
    """明确的来源类型优先于容器名称。"""
    assert _resolve_doc_marker("Example proceedings", source_type, "") == expected


# 引用降级不得删除枚举项或在反复规范化中累积重复说明。
def test_citation_normalization_preserves_sequence_and_is_idempotent() -> None:
    """保留三项枚举的位置、段落和后续说明。"""
    result: dict[str, Any] = {
        "research_purpose": "一是文献[1]证明效率提高。二是文献[2]发现体验改善。三是制定研究计划。\n下一阶段核对资料。",
        "references": [{"index": 1, "title": "主题甲"}, {"index": 2, "title": "主题乙"}],
    }
    normalize_citation_claims(result)
    text = result["research_purpose"]
    assert text.index("一是") < text.index("二是") < text.index("三是")
    assert "提高" not in text and "改善" not in text
    assert "\n下一阶段" in text
    normalize_citation_claims(result)
    assert result["research_purpose"] == text


# 枚举项互相依赖，不能为满足预算删掉其中一项。
def test_sentence_trimming_keeps_dependent_enumeration() -> None:
    """不足以容纳完整枚举时交由重写，不机械删除某个编号。"""
    text = "一是" + "甲" * 60 + "。二是" + "乙" * 60 + "。三是" + "丙" * 60 + "。"
    assert llm_service._trim_to_complete_sentences(text, "research_purpose", 80, 150) == text


# 单周计划不显示同一周两次。
def test_single_week_schedule_is_compact() -> None:
    """只合并相同起止周，不改变任务内容。"""
    assert _schedule_text([{"start": "第5周", "end": "第5周", "task": "检查", "deliverable": "记录"}]).startswith("第5周：")


# 用最小任务书检查固定列宽、重复表头和真实页码域。
def test_task_book_layout_and_task_labels(tmp_path: Path) -> None:
    """生成产物应保留任务目标语义，内容列大于标签列。"""
    path = tmp_path / "task.docx"
    build_thesis_material_document(
        document_type="task_book", title="测试课题", request={}, references=[], output_path=path,
        result={"module_tasks": [{"name": "分析", "role": "确定研究范围。", "responsibilities": "梳理资料。", "boundary": "仅限公开资料。"}]},
    )
    doc = Document(str(path))
    assert doc.tables[-1].columns[1].width > doc.tables[-1].columns[0].width
    assert doc.tables[1].rows[0]._tr.find(".//" + qn("w:tblHeader")) is not None
    assert "PAGE" in doc.sections[0].footer._element.xml
    body = "".join(cell.text for table in doc.tables for row in table.rows for cell in row.cells)
    assert "面向确定" not in body and "。，" not in body


# 参考文献使用独立不可拆行，避免一条来源被分页截断。
def test_task_book_references_are_independent_unsplit_rows(tmp_path: Path) -> None:
    """两条参考文献分别占一行，后续审核区仍完整保留。"""
    path = tmp_path / "references.docx"
    references = [ReferenceRecord(index=n, title=f"来源{n}", formatted=f"[{n}] 来源{n}") for n in (1, 2)]
    build_thesis_material_document(
        document_type="task_book", title="课题", request={}, result={}, references=references, output_path=path,
    )
    table = Document(str(path)).tables[-1]
    for index, reference in enumerate(references, start=2):
        assert table.cell(index, 1).text == reference.formatted
        assert table.rows[index]._tr.find(".//" + qn("w:cantSplit")) is not None
    assert table.cell(4, 0).text == "指导教师"
    assert table.cell(6, 0).text == "二级学院审核意见"
