"""通用论文材料生成管线。"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from core.config import get_settings
from services.thesis.generation.progress import publish_progress, stage_context
from services.thesis_material.document_builder import build_thesis_material_document
from services.thesis_material.llm_service import (
    LITERATURE_BODY_FIELDS,
    TASK_BODY_FIELDS,
    _trim_to_character_limit,
    build_length_plan,
    generate_literature_review_content,
    generate_proposal_content,
    generate_task_book_content,
    normalize_citation_claims,
    repair_length_constraints,
    repair_reference_coverage,
    task_body_length,
    text_length,
)
from services.thesis_material.profile_policy import missing_profile_fields
from services.thesis_material.reference_service import reference_quality_summary, retrieve_reference_records

_CITATION = re.compile(r"\[(\d+)\]")
_NUMERIC_CITATION = re.compile(r"\[\s*\d+(?:\s*[,，\-–]\s*\d+)*\s*\]")
_NON_BODY_FIELDS = {
    "title",
    "references",
    "approval",
    "source_outline",
    "thesis_config",
    "writing_outline",
    "material_outline",
    "source_outline_origin",
    "missing_profile_fields",
}
PersistPlanCallable = Callable[[dict[str, Any]], Awaitable[None]]

_MATERIAL_SECTIONS: dict[str, tuple[tuple[str, str], ...]] = {
    "proposal_report": (
        ("research_purpose", "研究目的"),
        ("research_status_and_trends", "研究现状与发展趋势"),
        ("research_content", "研究内容"),
        ("research_methods", "研究重点、难点与方法"),
        ("feasibility_and_innovation", "可行性与创新点"),
        ("writing_outline", "论文写作提纲"),
        ("schedule", "进度计划"),
        ("references", "参考文献"),
    ),
    "literature_review": (
        ("abstract", "摘要"),
        ("introduction", "引言"),
        ("domestic_research", "国内研究现状"),
        ("foreign_research", "国外研究现状"),
        ("themes", "主题分类与代表性研究"),
        ("method_comparison", "研究方法比较"),
        ("research_gaps", "现有研究不足"),
        ("future_trends", "发展趋势"),
        ("conclusion", "结论"),
        ("references", "参考文献"),
    ),
    "task_book": (
        ("design_background", "课题背景"),
        ("design_goals", "设计目标"),
        ("module_tasks", "主要任务"),
        ("schedule_items", "进度安排"),
        ("deliverable_forms", "成果形式"),
        ("deliverable_requirements", "成果要求"),
        ("main_indicators", "主要指标"),
        ("references", "参考资料"),
    ),
}

PROPOSAL_SCHEDULE = (
    ("明确选题与研究问题，查阅基础资料", "选题说明与资料清单"),
    ("梳理相关研究并完成开题报告", "开题报告"),
    ("确定研究对象、方法与实施范围", "研究或设计方案"),
    ("收集资料并开展阶段性研究或设计", "阶段成果记录"),
    ("继续实施课题并整理主要成果", "研究资料或设计成果"),
    ("检查成果并开展必要的验证与分析", "验证与分析记录"),
    ("归纳研究发现、局限与改进方向", "研究总结"),
    ("撰写并检查论文初稿", "论文初稿"),
    ("根据指导意见修订定稿并准备答辩", "论文定稿与答辩材料"),
)

TASK_BOOK_SCHEDULE = (
    ("查阅资料并明确课题目标与范围", "资料清单与目标说明"),
    ("确定研究方法或设计方案", "课题实施方案"),
    ("开展课题主要研究或设计工作", "阶段成果"),
    ("检查成果并完成必要的验证与分析", "验证与分析记录"),
    ("整理、修订并提交毕业设计成果", "毕业设计成果"),
)


async def generate_thesis_material_document(
    *,
    task_id: str,
    document_type: str,
    request_payload: dict[str, Any],
    persist_plan: PersistPlanCallable | None = None,
) -> dict[str, Any]:
    """生成结构化内容和 DOCX，返回任务完成所需元数据。"""

    title = str(request_payload.get("title") or "").strip()
    if not title:
        raise RuntimeError("文档标题不能为空")
    await publish_progress(task_id, "planning", "正在确定论文大纲和材料结构", progress=10)
    with stage_context("planning"):
        await prepare_material_plan(document_type, request_payload)
        if persist_plan is not None:
            await persist_plan(request_payload)
    await publish_progress(
        task_id,
        "planning",
        "材料大纲已确定",
        progress=18,
        source_outline=request_payload["source_outline"],
        material_outline=request_payload["material_outline"],
    )
    options = request_payload["thesis_config"]
    chinese_count = int(options["chinese_reference_count"])
    english_count = int(options["english_reference_count"])
    references = []
    if document_type in {"proposal_report", "literature_review", "task_book"}:
        await publish_progress(task_id, "retrieving_references", "正在检索和整理真实参考文献", progress=22)
        with stage_context("retrieving_references"):
            references = await retrieve_reference_records(
                title,
                _research_context_text(request_payload),
                chinese_reference_count=chinese_count,
                english_reference_count=english_count,
            )

    await publish_progress(task_id, "generating_sections", "正在分段生成文档内容", progress=40)
    with stage_context("generating_sections"):
        if document_type == "proposal_report":
            result = await generate_proposal_content(request_payload, references)
            result["schedule"] = _build_schedule(PROPOSAL_SCHEDULE, default_weeks=16)
            result["approval"] = _empty_approval("指导教师意见", "教研室（学术小组）意见")
        elif document_type == "literature_review":
            result = await generate_literature_review_content(request_payload, references)
        elif document_type == "task_book":
            result = await generate_task_book_content(request_payload)
            result["schedule_items"] = _build_schedule(TASK_BOOK_SCHEDULE, default_weeks=16)
            result["approval"] = _empty_approval("指导教师", "教研室审核意见", "二级学院审核意见")
        else:
            raise RuntimeError(f"不支持的文档类型: {document_type}")

    result["document_type"] = document_type
    result["title"] = title
    result["missing_profile_fields"] = missing_profile_fields(document_type)
    result["references"] = [item.model_dump(mode="json") for item in references]
    result["source_outline"] = request_payload["source_outline"]
    result["source_outline_origin"] = request_payload["source_outline_origin"]
    result["material_outline"] = request_payload["material_outline"]
    if request_payload.get("thesis_config"):
        result["thesis_config"] = request_payload["thesis_config"]

    await publish_progress(task_id, "validating", "正在校验结构、引用和个人信息", progress=72)
    with stage_context("validating"):
        if document_type in {"proposal_report", "literature_review"}:
            normalize_citation_claims(result)
        elif document_type in {"proposal_report", "literature_review", "task_book"}:
            _remove_inline_citations(document_type, result)
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
    result["reference_quality"] = reference_quality_summary(
        references,
        chinese_reference_count=chinese_count,
        english_reference_count=english_count,
    )
    result["quality_warnings"] = result["reference_quality"]["warnings"]
    # 当前文献记录是题录，不具有摘要/全文证据；不能把引用闭环当作内容已核验。
    if references and document_type in {"proposal_report", "literature_review"}:
        result["quality_warnings"] = [*result["quality_warnings"], "reference_evidence_limited"]
        result["reference_evidence_notice"] = "当前仅核验文献题录，方法、结果及比较结论仍需结合原文审阅。"
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


async def prepare_material_plan(document_type: str, request_payload: dict[str, Any]) -> None:
    """基于已确认大纲形成可在任务重试中复用的材料结构。"""

    if document_type not in _MATERIAL_SECTIONS:
        raise RuntimeError(f"不支持的文档类型: {document_type}")
    source_outline = request_payload.get("source_outline")
    if not source_outline:
        raise ValueError("请先生成并确认论文大纲")
    request_payload.setdefault("source_outline_origin", "user_confirmed")
    if request_payload.get("material_outline"):
        return
    chapter_titles = [str(chapter["chapter"]) for chapter in source_outline]
    request_payload["material_outline"] = {
        "document_type": document_type,
        "source_chapters": chapter_titles,
        "sections": [
            {
                "key": key,
                "title": title,
                "focus_chapters": _material_section_focus(key, chapter_titles),
            }
            for key, title in _MATERIAL_SECTIONS[document_type]
        ],
    }


def _material_section_focus(key: str, chapter_titles: list[str]) -> list[str]:
    """按材料章节用途引用已确认论文大纲的相关部分。"""

    if key in {"references", "schedule", "schedule_items"}:
        return []
    if key in {"abstract", "introduction", "research_purpose", "design_background"}:
        return chapter_titles[:2]
    if key in {"conclusion", "future_trends", "research_gaps"}:
        return chapter_titles[-2:]
    return chapter_titles


def _build_schedule(
    templates: tuple[tuple[str, str], ...],
    *,
    default_weeks: int,
) -> list[dict[str, str]]:
    total_weeks = default_weeks
    items: list[dict[str, str]] = []
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
        text_parts = _collect_text(result, ignored_keys=_NON_BODY_FIELDS)
        citations = {int(value) for value in _CITATION.findall("\n".join(text_parts))}
        invalid = sorted(index for index in citations if index < 1 or index > reference_count)
        if invalid:
            raise RuntimeError(f"正文包含无效参考文献编号: {invalid}")
        if reference_count and not citations:
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
            raise RuntimeError(f"字段{field}字数{length}不在{validation_minimum}-{validation_maximum}范围内")
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
    if document_type in {"proposal_report", "literature_review", "task_book"}:
        body_length = _material_body_char_count(document_type, result)
        if not plan.body_minimum <= body_length <= plan.body_maximum:
            raise RuntimeError(f"正文总字数{body_length}不在{plan.body_minimum}-{plan.body_maximum}范围内")
    if document_type == "task_book":
        if len(result.get("design_goals", [])) not in range(5, 11):
            raise RuntimeError("任务书设计目标数量不合法")
        if len(result.get("module_tasks", [])) not in range(4, 9):
            raise RuntimeError("任务书模块任务数量不合法")
        if len(result.get("main_indicators", [])) not in range(4, 9):
            raise RuntimeError("任务书主要指标数量不合法")
    if document_type == "proposal_report":
        outline = result.get("writing_outline")
        source_outline = request.get("source_outline") or []
        expected = len(source_outline)
        if (
            not isinstance(outline, list)
            or (expected and len(outline) != expected)
            or (not expected and not 1 <= len(outline) <= 20)
        ):
            raise RuntimeError("开题报告写作提纲数量不合法")


def _remove_inline_citations(document_type: str, result: dict[str, Any]) -> None:
    """不标注模式仅移除正文编号，保留完整的真实文献列表。"""

    if document_type == "task_book":
        for field in (
            "design_background",
            "design_goals",
            "module_tasks",
            "deliverable_forms",
            "deliverable_requirements",
            "main_indicators",
        ):
            if field in result:
                result[field] = _strip_numeric_citations(result[field])
        return
    fields = (
        tuple(build_length_plan(document_type, {}).fields)
        if document_type == "proposal_report"
        else LITERATURE_BODY_FIELDS
    )
    for field in fields:
        if isinstance(result.get(field), str):
            result[field] = _NUMERIC_CITATION.sub("", result[field])
    if document_type == "literature_review":
        themes = result.get("themes")
        if isinstance(themes, list):
            for theme in themes:
                if isinstance(theme, dict) and isinstance(theme.get("content"), str):
                    theme["content"] = _NUMERIC_CITATION.sub("", theme["content"])


def _strip_numeric_citations(value: Any) -> Any:
    if isinstance(value, str):
        return _NUMERIC_CITATION.sub("", value)
    if isinstance(value, list):
        return [_strip_numeric_citations(item) for item in value]
    if isinstance(value, dict):
        return {key: _strip_numeric_citations(item) for key, item in value.items()}
    return value


def _missing_reference_indexes(
    document_type: str,
    result: dict[str, Any],
    reference_count: int,
) -> list[int]:
    if reference_count <= 0:
        return []
    text_parts = _collect_text(result, ignored_keys=_NON_BODY_FIELDS)
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


def _safe_filename(title: str) -> str:
    value = re.sub(r"[\\/:*?\"<>|]", "_", title).strip(" .")
    return value[:80] or "thesis-material"


def _material_body_char_count(document_type: str, result: dict[str, Any]) -> int:
    """按产品约定统计正文非空白字符，不计结构、计划、参考文献和个人信息。"""
    if document_type == "task_book":
        return task_body_length(result)

    if document_type == "proposal_report":
        fields = tuple(build_length_plan(document_type, {}).fields)
    elif document_type == "literature_review":
        fields = LITERATURE_BODY_FIELDS
    else:
        return sum(text_length(str(result.get(field) or "")) for field in ("design_background",))
    total = sum(text_length(str(result.get(field) or "")) for field in fields)
    themes = result.get("themes")
    if document_type == "literature_review" and isinstance(themes, list):
        total += sum(text_length(str(theme.get("content") or "")) for theme in themes if isinstance(theme, dict))
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
    candidates: tuple[str, ...]
    if document_type == "proposal_report":
        field = "research_content"
        candidates = (
            "研究过程还将结合课题对象的实际条件，明确研究边界，并对所采用的方法与资料来源进行检查。",
            "各阶段的分析、实施与验证结果将形成可追溯关系，使研究内容和论证过程能够被复核。",
            "最终方案将根据验证结果进行修订，并明确尚待后续研究的问题。",
        )
    elif document_type == "literature_review":
        field = "conclusion"
        candidates = (
            "综合现有研究，后续仍需结合本课题的具体研究对象与应用条件，对主要观点开展进一步验证。",
            "相关结论的适用边界应通过可复核的资料、方法和实际反馈进一步说明。",
            "上述研究线索为本课题的问题界定、方法选择和评价设计提供了审慎依据。",
        )
        source_outline = request.get("source_outline")
        if isinstance(source_outline, list):
            # 固定补充语仍不足时，依据用户确认的章节提出后续核查方向，不补造研究结论。
            for chapter in source_outline:
                if isinstance(chapter, dict) and (title := str(chapter.get("chapter") or "").strip()):
                    candidates += (
                        f"围绕“{title}”涉及的问题，后续需要对研究对象、证据来源与方法边界逐项核查，"
                        "并明确可复核的评价路径。",
                    )
            for chapter in source_outline:
                if not isinstance(chapter, dict):
                    continue
                for section in chapter.get("sections") or []:
                    if isinstance(section, dict) and (title := str(section.get("name") or "").strip()):
                        candidates += (f"针对“{title}”，后续研究需要说明资料选择依据、比较维度及论证的适用范围。",)
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
    included_fields = list(TASK_BODY_FIELDS) if document_type == "task_book" else list(plan.fields)
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
            "schedule_items",
            "technology_stack",
            "title",
            "keywords",
            "writing_outline",
            "schedule",
            "references",
            "approval",
            "signature_area",
        ],
    }


__all__ = ["generate_thesis_material_document"]
