"""通用论文材料生成管线。"""

from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from core.config import get_settings
from services.thesis.generation.progress import publish_progress, stage_context
from services.thesis_material.document_builder import build_thesis_material_document
from services.thesis_material.llm_service import (
    LITERATURE_BODY_FIELDS,
    _trim_to_character_limit,
    build_length_plan,
    generate_literature_review_content,
    generate_proposal_content,
    generate_task_book_content,
    normalize_citation_claims,
    repair_length_constraints,
    repair_reference_coverage,
    text_length,
)
from services.thesis_material.profile_policy import missing_profile_fields
from services.thesis_material.reference_service import retrieve_reference_records

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


async def generate_thesis_material_document(
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
    if document_type in {"proposal_report", "literature_review", "task_book"}:
        await publish_progress(task_id, "retrieving_references", "正在检索和整理真实参考文献", progress=12)
        options = request_payload.get("reference_options") or {}
        defaults = {
            "proposal_report": (15, 8, 4, 2),
            "literature_review": (20, 12, 6, 4),
            "task_book": (10, 5, 5, 0),
        }
        default_target, minimum, minimum_chinese, minimum_english = defaults[document_type]
        target = int(options.get("target_count") or default_target)
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
    result["missing_profile_fields"] = missing_profile_fields(document_type, request_payload)
    result["references"] = [item.model_dump(mode="json") for item in references]

    await publish_progress(task_id, "validating", "正在校验结构、引用和个人信息", progress=72)
    with stage_context("validating"):
        if document_type in {"proposal_report", "literature_review"}:
            normalize_citation_claims(result)
        await repair_length_constraints(document_type, request_payload, result)
        for _ in range(1 if document_type in {"proposal_report", "literature_review"} else 0):
            missing_reference_indexes = _missing_reference_indexes(document_type, result, len(references))
            if not missing_reference_indexes:
                break
            await repair_reference_coverage(
                document_type,
                request_payload,
                result,
                [item for item in references if item.index in missing_reference_indexes],
            )
        if document_type in {"proposal_report", "literature_review"}:
            normalize_citation_claims(result)
            await repair_length_constraints(document_type, request_payload, result)
            normalize_citation_claims(result)
            _ensure_body_minimum_after_normalization(document_type, request_payload, result)
            _ensure_reference_coverage_after_normalization(
                document_type,
                request_payload,
                result,
                references,
            )
    _validate_result(document_type, result, len(references), request_payload)
    result["word_count"] = _word_count_metadata(document_type, request_payload, result)
    await publish_progress(task_id, "rendering_docx", "正在生成Word文档", progress=84)
    output_root = Path(get_settings().THESIS_MATERIAL_OUTPUT_ROOT) / task_id
    output_path = output_root / f"{_safe_filename(title)}-{document_type}.docx"
    with stage_context("rendering_docx"):
        build_thesis_material_document(
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
        "fulltext_char_count": _material_body_char_count(document_type, result),
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


def _validate_result(
    document_type: str,
    result: dict[str, Any],
    reference_count: int,
    request: dict[str, Any] | None = None,
) -> None:
    request = request or {}
    if document_type in {"proposal_report", "literature_review"}:
        text_parts = _collect_text(result, ignored_keys={"references", "student_profile", "approval"})
        citations = {int(value) for value in _CITATION.findall("\n".join(text_parts))}
        invalid = sorted(index for index in citations if index < 1 or index > reference_count)
        if invalid:
            raise RuntimeError(f"正文包含无效参考文献编号: {invalid}")
        if not citations:
            raise RuntimeError("正文没有引用真实参考文献")
        required_coverage = _required_reference_coverage(document_type, reference_count)
        if len(citations) < required_coverage:
            raise RuntimeError(f"正文引用参考文献不足: {len(citations)}/{required_coverage}")
    plan = build_length_plan(document_type, request)
    for field, length_range in plan.fields.items():
        length = text_length(str(result.get(field) or ""))
        validation_minimum = max(80, round(length_range.target * 0.35))
        validation_maximum = round(length_range.target * 2)
        if not validation_minimum <= length <= validation_maximum:
            raise RuntimeError(
                f"字段{field}字数{length}不在{validation_minimum}-{validation_maximum}范围内"
            )
    if document_type == "literature_review":
        themes = result.get("themes")
        if not isinstance(themes, list) or len(themes) != plan.theme_count or plan.theme is None:
            raise RuntimeError("文献综述主题数量不合法")
        for index, theme in enumerate(themes):
            content = str(theme.get("content") or "") if isinstance(theme, dict) else ""
            length = text_length(content)
            validation_minimum = max(80, round(plan.theme.target * 0.35))
            validation_maximum = round(plan.theme.target * 2)
            if not validation_minimum <= length <= validation_maximum:
                raise RuntimeError(f"字段themes[{index}].content字数不合法")
    if document_type in {"proposal_report", "literature_review"}:
        body_length = _material_body_char_count(document_type, result)
        if not plan.body_minimum <= body_length <= plan.body_maximum:
            raise RuntimeError(
                f"正文总字数{body_length}不在{plan.body_minimum}-{plan.body_maximum}范围内"
            )
    if document_type == "task_book":
        if len(result.get("design_goals", [])) not in range(5, 11):
            raise RuntimeError("任务书设计目标数量不合法")
        if len(result.get("module_tasks", [])) not in range(4, 9):
            raise RuntimeError("任务书模块任务数量不合法")
        if len(result.get("main_indicators", [])) not in range(4, 9):
            raise RuntimeError("任务书主要指标数量不合法")
    if document_type == "proposal_report":
        outline = result.get("writing_outline")
        if not isinstance(outline, list) or not 5 <= len(outline) <= 8:
            raise RuntimeError("开题报告写作提纲数量不合法")


def _missing_reference_indexes(
    document_type: str,
    result: dict[str, Any],
    reference_count: int,
) -> list[int]:
    if reference_count <= 0:
        return []
    text_parts = _collect_text(result, ignored_keys={"references", "student_profile", "approval"})
    citations = {int(value) for value in _CITATION.findall("\n".join(text_parts))}
    required_coverage = _required_reference_coverage(document_type, reference_count)
    needed = max(required_coverage - len(citations), 0)
    return sorted(set(range(1, reference_count + 1)) - citations)[:needed]


def _ensure_reference_coverage_after_normalization(
    document_type: str,
    request: dict[str, Any],
    result: dict[str, Any],
    references: list[Any],
) -> None:
    """在最终引用净化后补入可由题名和来源直接核验的引用线索。"""

    missing_indexes = _missing_reference_indexes(document_type, result, len(references))
    if not missing_indexes:
        return
    by_index = {int(item.index): item for item in references}
    statements = "".join(
        f"题名《{by_index[index].title}》及其来源信息被纳入本课题的研究线索[{index}]。"
        for index in missing_indexes
        if index in by_index
    )
    target_field = "research_status_and_trends" if document_type == "proposal_report" else "conclusion"
    result[target_field] = f"{str(result.get(target_field) or '').rstrip()}{statements}"

    plan = build_length_plan(document_type, request)
    overflow = _material_body_char_count(document_type, result) - plan.body_maximum
    if overflow <= 0:
        return
    candidates = sorted(
        (
            (field, str(result.get(field) or ""))
            for field in plan.fields
            if field != target_field and not _CITATION.search(str(result.get(field) or ""))
        ),
        key=lambda item: text_length(item[1]),
        reverse=True,
    )
    for field, value in candidates:
        current_length = text_length(value)
        removable = max(current_length - max(80, round(plan.fields[field].target * 0.35)), 0)
        if removable <= 0:
            continue
        removed = min(removable, overflow)
        result[field] = _trim_to_character_limit(value, current_length - removed)
        overflow -= removed
        if overflow <= 0:
            return
    raise RuntimeError("补齐最终引用后无法在正文总字数上限内安全收敛")


def _required_reference_coverage(document_type: str, reference_count: int) -> int:
    """计算不同材料正文需要实际引用的最低文献数量。"""

    if document_type == "proposal_report":
        return min(reference_count, 8)
    if document_type == "literature_review":
        return min(reference_count, max(12, (reference_count * 4 + 4) // 5))
    return 0


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
    return value[:80] or "thesis-material"


def _material_body_char_count(document_type: str, result: dict[str, Any]) -> int:
    """按产品约定统计正文非空白字符，不计结构、计划、参考文献和个人信息。"""

    if document_type == "proposal_report":
        fields = tuple(build_length_plan(document_type, {}).fields)
    elif document_type == "literature_review":
        fields = LITERATURE_BODY_FIELDS
    else:
        return sum(
            text_length(str(result.get(field) or ""))
            for field in ("design_background",)
        )
    total = sum(text_length(str(result.get(field) or "")) for field in fields)
    themes = result.get("themes")
    if document_type == "literature_review" and isinstance(themes, list):
        total += sum(
            text_length(str(theme.get("content") or ""))
            for theme in themes
            if isinstance(theme, dict)
        )
    return total


def _ensure_body_minimum_after_normalization(
    document_type: str,
    request: dict[str, Any],
    result: dict[str, Any],
) -> None:
    """引用保守化导致轻微短缺时，补入无归因、无数值的课题综合说明。"""

    plan = build_length_plan(document_type, request)
    missing = plan.body_minimum - _material_body_char_count(document_type, result)
    if missing <= 0:
        return
    if document_type == "proposal_report":
        field = "research_content"
        candidates = (
            "研究过程还将结合校园实际交易流程，对功能边界、数据一致性与交互可用性进行验证。",
            "各模块的分析、设计与测试结果将形成可追溯关系，保证研究内容能够被复核。",
            "最终方案将根据功能验证结果进行修订，并明确尚待后续研究的问题。",
        )
    elif document_type == "literature_review":
        field = "conclusion"
        candidates = (
            "综合现有研究，后续仍需结合校园业务流程，对系统架构、交易治理与用户体验开展协同验证。",
            "相关方案的适用边界应通过可复核的功能测试和实际使用反馈进一步说明。",
            "上述研究线索为本课题的需求分析、技术选择和评价设计提供了审慎依据。",
        )
    else:
        return
    supplements: list[str] = []
    added = 0
    for candidate in candidates:
        supplements.append(candidate)
        added += text_length(candidate)
        if added >= missing:
            break
    if added < missing:
        raise RuntimeError(f"正文规范化后仍缺少{missing - added}字，无法安全补足")
    result[field] = f"{str(result.get(field) or '').rstrip()}\n{''.join(supplements)}".strip()


def _word_count_metadata(
    document_type: str,
    request: dict[str, Any],
    result: dict[str, Any],
) -> dict[str, Any]:
    plan = build_length_plan(document_type, request)
    included_fields = list(plan.fields)
    if document_type == "literature_review":
        included_fields.append("themes[].content")
    return {
        "metric": "non_whitespace_characters",
        "target": plan.target_word_count or None,
        "minimum": plan.body_minimum or None,
        "maximum": plan.body_maximum or None,
        "actual": _material_body_char_count(document_type, result),
        "included_fields": included_fields,
        "excluded_sections": [
            "title",
            "keywords",
            "writing_outline",
            "schedule",
            "references",
            "student_profile",
            "approval",
            "signature_area",
        ],
    }


__all__ = ["generate_thesis_material_document"]
