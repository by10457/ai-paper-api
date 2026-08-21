"""通用学术材料生成管线。"""

from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from core.config import get_settings
from services.thesis.generation.progress import publish_progress, stage_context
from services.writing.document_builder import build_writing_document
from services.writing.llm_service import (
    LITERATURE_BODY_LENGTH,
    LITERATURE_THEME_LENGTH,
    WRITING_LENGTH_CONSTRAINTS,
    generate_literature_review_content,
    generate_proposal_content,
    generate_task_book_content,
    repair_length_constraints,
    repair_reference_coverage,
    text_length,
)
from services.writing.reference_service import retrieve_reference_records

_CITATION = re.compile(r"\[(\d+)\]")

PROPOSAL_SCHEDULE = (
    ("明确选题，查阅资料并完成开题报告", "开题报告"),
    ("学习相关技术并完成需求分析", "需求分析文档"),
    ("完成总体设计和功能模块划分", "总体设计方案"),
    ("完成数据库和数据关系设计", "数据库设计文档"),
    ("实现后端或核心功能模块", "核心功能代码"),
    ("实现界面并完成接口联调", "可运行系统"),
    ("执行功能、性能与安全测试并修复问题", "测试报告"),
    ("整理成果并完成论文初稿", "论文初稿"),
    ("根据意见修改定稿并准备答辩", "论文定稿与答辩材料"),
)

TASK_BOOK_SCHEDULE = (
    ("查阅资料并完成需求分析", "需求分析文档"),
    ("完成原型、业务流程和数据设计", "原型与设计文档"),
    ("实现课题核心功能", "可运行项目代码"),
    ("编写测试计划并完成系统测试", "测试报告"),
    ("整理并完成毕业设计成果", "毕业设计成果"),
)


async def generate_writing_document(
    *,
    task_id: str,
    document_type: str,
    request_payload: dict[str, Any],
) -> dict[str, Any]:
    """生成结构化内容和 DOCX，返回任务完成所需元数据。"""

    title = str(request_payload.get("title") or "").strip()
    if not title:
        raise RuntimeError("文档标题不能为空")
    references = []
    if document_type in {"proposal_report", "literature_review"}:
        await publish_progress(task_id, "retrieving_references", "正在检索和整理真实参考文献", progress=12)
        options = request_payload.get("reference_options") or {}
        target = int(options.get("target_count") or (15 if document_type == "proposal_report" else 20))
        minimum = 8 if document_type == "proposal_report" else 12
        minimum_chinese = 6 if document_type == "proposal_report" else 8
        minimum_english = 2 if document_type == "proposal_report" else 4
        with stage_context("retrieving_references"):
            references = await retrieve_reference_records(
                title,
                _research_context_text(request_payload),
                target_count=target,
                minimum_count=minimum,
                minimum_chinese_count=minimum_chinese,
                minimum_english_count=minimum_english,
            )

    await publish_progress(task_id, "planning", "正在规划文档结构", progress=28)
    await publish_progress(task_id, "generating_sections", "正在分段生成文档内容", progress=40)
    with stage_context("generating_sections"):
        if document_type == "proposal_report":
            result = await generate_proposal_content(request_payload, references)
            result["schedule"] = _build_schedule(request_payload, PROPOSAL_SCHEDULE, default_weeks=16)
            result["approval"] = _empty_approval("指导教师意见", "教研室（学术小组）意见")
        elif document_type == "literature_review":
            result = await generate_literature_review_content(request_payload, references)
        elif document_type == "task_book":
            result = await generate_task_book_content(request_payload)
            result["schedule_items"] = _build_schedule(request_payload, TASK_BOOK_SCHEDULE, default_weeks=20)
            result["approval"] = _empty_approval("指导教师", "教研室审核意见", "二级学院审核意见")
        else:
            raise RuntimeError(f"不支持的文档类型: {document_type}")

    result["document_type"] = document_type
    result["title"] = title
    result["student_profile"] = request_payload.get("student_profile") or {}
    result["references"] = [item.model_dump(mode="json") for item in references]

    await publish_progress(task_id, "validating", "正在校验结构、引用和个人信息", progress=72)
    await repair_length_constraints(document_type, request_payload, result)
    for _ in range(2):
        missing_reference_indexes = _missing_reference_indexes(result, len(references))
        if not missing_reference_indexes:
            break
        await repair_reference_coverage(
            document_type,
            request_payload,
            result,
            [item for item in references if item.index in missing_reference_indexes],
        )
        await repair_length_constraints(document_type, request_payload, result)
    _validate_result(document_type, result, len(references))
    await publish_progress(task_id, "rendering_docx", "正在生成Word文档", progress=84)
    output_root = Path(get_settings().WRITING_OUTPUT_ROOT) / task_id
    output_path = output_root / f"{_safe_filename(title)}-{document_type}.docx"
    with stage_context("rendering_docx"):
        build_writing_document(
            document_type=document_type,
            title=title,
            request=request_payload,
            result=result,
            references=references,
            output_path=output_path,
        )
    return {
        "docx_path": str(output_path),
        "document_type": document_type,
        "result_data": result,
        "fulltext_char_count": _result_char_count(result),
        "figure_count": 0,
        "mermaid_count": 0,
        "chart_count": 0,
        "ai_image_count": 0,
        "fallback_count": 0,
        "truncation_warning": False,
    }


def _build_schedule(
    request: dict[str, Any],
    templates: tuple[tuple[str, str], ...],
    *,
    default_weeks: int,
) -> list[dict[str, str]]:
    options = request.get("schedule_options") or {}
    start_date = _parse_date(options.get("start_date"))
    end_date = _parse_date(options.get("end_date"))
    total_weeks = int(options.get("total_weeks") or default_weeks)
    items: list[dict[str, str]] = []
    if start_date and end_date:
        total_days = max((end_date - start_date).days + 1, len(templates))
        for index, (task, deliverable) in enumerate(templates):
            item_start = start_date + timedelta(days=round(total_days * index / len(templates)))
            item_end = start_date + timedelta(days=round(total_days * (index + 1) / len(templates)) - 1)
            if index == len(templates) - 1:
                item_end = end_date
            items.append(
                {
                    "start": item_start.isoformat(),
                    "end": item_end.isoformat(),
                    "task": task,
                    "deliverable": deliverable,
                }
            )
        return items

    for index, (task, deliverable) in enumerate(templates):
        start_week = round(total_weeks * index / len(templates)) + 1
        end_week = max(start_week, round(total_weeks * (index + 1) / len(templates)))
        items.append(
            {
                "start": f"第{start_week}周",
                "end": f"第{end_week}周",
                "task": task,
                "deliverable": deliverable,
            }
        )
    return items


def _validate_result(document_type: str, result: dict[str, Any], reference_count: int) -> None:
    if document_type in {"proposal_report", "literature_review"}:
        text_parts = _collect_text(result, ignored_keys={"references", "student_profile", "approval"})
        citations = {int(value) for value in _CITATION.findall("\n".join(text_parts))}
        invalid = sorted(index for index in citations if index < 1 or index > reference_count)
        if invalid:
            raise RuntimeError(f"正文包含无效参考文献编号: {invalid}")
        if not citations:
            raise RuntimeError("正文没有引用真实参考文献")
        missing = sorted(set(range(1, reference_count + 1)) - citations)
        if missing:
            raise RuntimeError(f"文末参考文献未在正文引用: {missing}")
    for field, (minimum, maximum) in WRITING_LENGTH_CONSTRAINTS.get(document_type, {}).items():
        length = text_length(str(result.get(field) or ""))
        if not minimum <= length <= maximum:
            raise RuntimeError(f"字段{field}字数{length}不在{minimum}-{maximum}范围内")
    if document_type == "literature_review":
        themes = result.get("themes")
        if not isinstance(themes, list) or not 3 <= len(themes) <= 6:
            raise RuntimeError("文献综述主题数量不合法")
        for index, theme in enumerate(themes):
            content = str(theme.get("content") or "") if isinstance(theme, dict) else ""
            length = text_length(content)
            if not LITERATURE_THEME_LENGTH[0] <= length <= LITERATURE_THEME_LENGTH[1]:
                raise RuntimeError(f"字段themes[{index}].content字数不合法")
        body_length = _literature_body_char_count(result)
        if not LITERATURE_BODY_LENGTH[0] <= body_length <= LITERATURE_BODY_LENGTH[1]:
            raise RuntimeError(f"文献综述正文字数{body_length}不在目标范围内")
    if document_type == "task_book":
        if len(result.get("design_goals", [])) not in range(5, 11):
            raise RuntimeError("任务书设计目标数量不合法")
        if len(result.get("module_tasks", [])) not in range(4, 9):
            raise RuntimeError("任务书模块任务数量不合法")


def _missing_reference_indexes(result: dict[str, Any], reference_count: int) -> list[int]:
    if reference_count <= 0:
        return []
    text_parts = _collect_text(result, ignored_keys={"references", "student_profile", "approval"})
    citations = {int(value) for value in _CITATION.findall("\n".join(text_parts))}
    return sorted(set(range(1, reference_count + 1)) - citations)


def _collect_text(value: Any, *, ignored_keys: set[str]) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        result: list[str] = []
        for item in value:
            result.extend(_collect_text(item, ignored_keys=ignored_keys))
        return result
    if isinstance(value, dict):
        result = []
        for key, item in value.items():
            if key not in ignored_keys:
                result.extend(_collect_text(item, ignored_keys=ignored_keys))
        return result
    return []


def _empty_approval(*labels: str) -> list[dict[str, str]]:
    return [{"label": label, "opinion": "", "signature": "", "date": ""} for label in labels]


def _research_context_text(request: dict[str, Any]) -> str:
    context = request.get("research_context") or {}
    values = [request.get("title", ""), context.get("direction", "")]
    values.extend(context.get("technology_stack") or [])
    values.extend(context.get("core_features") or [])
    return "；".join(str(value).strip() for value in values if str(value).strip())


def _parse_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value:
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None
    return None


def _safe_filename(title: str) -> str:
    value = re.sub(r"[\\/:*?\"<>|]", "_", title).strip(" .")
    return value[:80] or "academic-writing"


def _result_char_count(result: dict[str, Any]) -> int:
    return sum(len(text) for text in _collect_text(result, ignored_keys={"references", "approval", "student_profile"}))


def _literature_body_char_count(result: dict[str, Any]) -> int:
    fields = (
        "abstract",
        "introduction",
        "domestic_research",
        "foreign_research",
        "method_comparison",
        "research_gaps",
        "future_trends",
        "conclusion",
    )
    total = sum(text_length(str(result.get(field) or "")) for field in fields)
    themes = result.get("themes")
    if isinstance(themes, list):
        total += sum(
            text_length(str(theme.get("content") or ""))
            for theme in themes
            if isinstance(theme, dict)
        )
    return total


__all__ = ["generate_writing_document"]
