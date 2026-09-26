"""三类论文材料的结构化大模型生成。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from llm.client import create_configured_llm
from schemas.thesis_material import ReferenceRecord


@dataclass(frozen=True)
class LengthRange:
    """单个正文区块的目标和提示范围。"""

    target: int
    minimum: int
    maximum: int


@dataclass(frozen=True)
class MaterialLengthPlan:
    """按用户目标字数分配后的材料正文预算。"""

    target_word_count: int
    fields: dict[str, LengthRange]
    theme_count: int
    theme: LengthRange | None
    body_minimum: int
    body_maximum: int


_DEFAULT_TARGETS = {"proposal_report": 4000, "literature_review": 6000}
_LENGTH_WEIGHTS: dict[str, tuple[tuple[str, int], ...]] = {
    "proposal_report": (
        ("research_purpose", 16),
        ("research_status_and_trends", 30),
        ("research_content", 17),
        ("key_points", 9),
        ("difficulties", 9),
        ("research_methods", 12),
        ("feasibility_and_innovation", 7),
    ),
    "literature_review": (
        ("abstract", 7),
        ("introduction", 10),
        ("domestic_research", 14),
        ("foreign_research", 14),
        ("method_comparison", 9),
        ("research_gaps", 6),
        ("future_trends", 5),
        ("conclusion", 5),
    ),
}
_LITERATURE_THEME_WEIGHT = 30


def build_length_plan(document_type: str, request: dict[str, Any]) -> MaterialLengthPlan:
    """把总正文目标按材料类型动态分配到各区块。

    统计口径统一为正文非空白字符数；不计标题、关键词、写作提纲、进度计划、
    参考文献、个人信息和签字审核区。章节预算允许约正负 10% 的结构弹性，总正文
    验收容差为目标的正负 10%，另保留最多 20 个字符的引用规范化缓冲。
    """

    if document_type not in _DEFAULT_TARGETS:
        return MaterialLengthPlan(0, {"design_background": LengthRange(150, 100, 200)}, 0, None, 0, 0)
    target = int(request.get("target_word_count") or _DEFAULT_TARGETS[document_type])
    field_targets = _allocate_targets(target, _LENGTH_WEIGHTS[document_type])
    fields = {field: _length_range(value) for field, value in field_targets.items()}
    theme_count = 0
    theme = None
    if document_type == "literature_review":
        theme_count = max(3, min(6, round(target / 1500)))
        theme_total = round(target * _LITERATURE_THEME_WEIGHT / 100)
        theme = _length_range(round(theme_total / theme_count))
    body_slack = min(20, max(10, round(target * 0.005)))
    return MaterialLengthPlan(
        target_word_count=target,
        fields=fields,
        theme_count=theme_count,
        theme=theme,
        body_minimum=max(0, round(target * 0.9) - body_slack),
        body_maximum=round(target * 1.1) + body_slack,
    )


def _allocate_targets(target: int, weights: tuple[tuple[str, int], ...]) -> dict[str, int]:
    allocated: dict[str, int] = {}
    used = 0
    reserved_weight = _LITERATURE_THEME_WEIGHT if sum(weight for _, weight in weights) < 100 else 0
    allocatable = round(target * (100 - reserved_weight) / 100)
    for index, (field, weight) in enumerate(weights):
        value = allocatable - used if index == len(weights) - 1 else round(target * weight / 100)
        allocated[field] = value
        used += value
    return allocated


def _length_range(target: int) -> LengthRange:
    margin = max(20, round(target * 0.1))
    return LengthRange(target, max(80, target - margin), target + margin)


_DEFAULT_PROPOSAL_PLAN = build_length_plan("proposal_report", {})
_DEFAULT_LITERATURE_PLAN = build_length_plan("literature_review", {})
WRITING_LENGTH_CONSTRAINTS: dict[str, dict[str, tuple[int, int]]] = {
    "proposal_report": {
        field: (length.minimum, length.maximum) for field, length in _DEFAULT_PROPOSAL_PLAN.fields.items()
    },
    "literature_review": {
        field: (length.minimum, length.maximum) for field, length in _DEFAULT_LITERATURE_PLAN.fields.items()
    },
    "task_book": {"design_background": (100, 200)},
}
assert _DEFAULT_LITERATURE_PLAN.theme is not None
LITERATURE_THEME_LENGTH = (
    _DEFAULT_LITERATURE_PLAN.theme.minimum,
    _DEFAULT_LITERATURE_PLAN.theme.maximum,
)
LITERATURE_BODY_LENGTH = (
    _DEFAULT_LITERATURE_PLAN.body_minimum,
    _DEFAULT_LITERATURE_PLAN.body_maximum,
)
LITERATURE_BODY_FIELDS = (
    "abstract",
    "introduction",
    "domestic_research",
    "foreign_research",
    "method_comparison",
    "research_gaps",
    "future_trends",
    "conclusion",
)

_FIELD_REQUIREMENTS = {
    "research_purpose": "涵盖行业背景、现实问题、技术背景、研究必要性、应用价值和研究目标。",
    "research_status_and_trends": "涵盖传统方案、国内外研究、主流技术、应用场景、架构演进、现有不足和未来趋势，并形成比较评价。",
    "research_content": "说明研究对象、主要内容、预期解决的问题以及各部分之间的逻辑关系。",
    "key_points": "说明系统架构、核心功能、数据设计和关键业务。",
    "difficulties": "说明性能、并发、数据一致性、安全、交互或算法难点。",
    "research_methods": "说明技术路线、框架、数据库、接口、测试和问题解决手段。",
    "feasibility_and_innovation": "从资料、技术、数据、时间和实施条件论证可行性，并提出审慎且可验证的创新点。",
    "abstract": "概括研究背景、综述范围、主要研究脉络、不足和本文切入点。",
    "introduction": "说明研究背景、综述目的、检索范围和组织思路。",
    "domestic_research": "综合比较国内代表性研究、主要方法、成果和局限，不得逐篇堆砌摘要。",
    "foreign_research": "综合比较国外代表性研究、主要方法、成果和适用条件，不得逐篇堆砌摘要。",
    "theme_content": "围绕单一主题比较多篇文献，必须包含已有做法、不同观点、优缺点和主题小结。",
    "method_comparison": "比较不同研究方法、数据、系统架构和适用条件。",
    "research_gaps": "归纳已有研究的不足、争议和未解决问题。",
    "future_trends": "依据已有研究推导可解释的发展方向。",
    "conclusion": "总结研究脉络以及本课题可以切入的位置。",
    "design_background": "说明课题目的、业务背景和预期价值。",
}

_FIELD_KEYWORD_GROUPS = {
    "research_purpose": (("背景",), ("问题",), ("技术",), ("必要",), ("价值",), ("目标",)),
    "research_status_and_trends": (
        ("传统",),
        ("国内",),
        ("国外",),
        ("技术",),
        ("应用",),
        ("架构",),
        ("不足", "局限"),
        ("趋势", "未来"),
    ),
    "research_content": (("对象", "课题"), ("内容",), ("问题",), ("关系", "逻辑")),
    "key_points": (("架构",), ("功能",), ("数据",), ("业务",)),
    "difficulties": (("性能", "并发"), ("一致性",), ("安全",), ("交互", "算法")),
    "research_methods": (("技术路线",), ("框架",), ("数据库",), ("接口",), ("测试",)),
    "feasibility_and_innovation": (("可行",), ("资料", "数据"), ("技术",), ("时间",), ("创新",)),
    "abstract": (("背景",), ("范围",), ("研究",), ("不足", "局限"), ("切入", "方向")),
    "introduction": (("背景",), ("目的",), ("范围",), ("结构", "组织")),
    "domestic_research": (("国内",), ("方法",), ("成果",), ("不足", "局限")),
    "foreign_research": (("国外",), ("方法",), ("成果",), ("适用", "局限")),
    "theme_content": (("做法", "方法"), ("观点", "差异"), ("优势", "优点"), ("不足", "局限"), ("小结", "总体")),
    "method_comparison": (("方法",), ("数据",), ("架构",), ("适用",)),
    "research_gaps": (("不足",), ("争议",), ("问题",)),
    "future_trends": (("趋势",), ("方向",), ("发展",)),
    "conclusion": (("脉络", "总结"), ("切入", "课题")),
    "design_background": (("目的",), ("背景",), ("价值",)),
}

_SENTENCE_BOUNDARY = re.compile(r"(?<=[。！？!?；;])\s*|\n+")
_UNSUPPORTED_CITATION_CLAIM = re.compile(
    r"发现|证明|验证|表明|揭示|显示|显著|提升|提高|降低|改善|证实|提出|构建了|实现了|设计了|"
    r"强调|采用|使用|引入|聚焦|关注|指出|认为|提到|探讨|分析|研究了|进行了"
)
_CITATION_TEXT_FIELDS = (
    "research_purpose",
    "research_status_and_trends",
    "abstract",
    "introduction",
    "domestic_research",
    "foreign_research",
    "method_comparison",
    "research_gaps",
    "future_trends",
    "conclusion",
)


async def generate_proposal_content(
    request: dict[str, Any],
    references: list[ReferenceRecord],
) -> dict[str, Any]:
    """分三次生成开题报告主体，避免单次长输出丢失区块。"""

    plan = build_length_plan("proposal_report", request)
    context = _request_context(request)
    reference_text = _reference_text(references)
    citation_instruction = _citation_instruction(request)
    purpose_range = plan.fields["research_purpose"]
    status_range = plan.fields["research_status_and_trends"]
    purpose = await _ask_text(
        "你是本科毕业设计开题报告写作专家。只输出连续正文，不要标题。",
        f"课题：{request['title']}\n补充信息：{context}\n"
        f"写{purpose_range.minimum}-{purpose_range.maximum}字研究目的，必须包括行业背景、现实问题、"
        f"技术背景、必要性、应用价值和研究目标。{citation_instruction}\n真实文献：\n{reference_text}",
        max_tokens=max(600, round(purpose_range.maximum * 1.2)),
    )
    status = await _ask_text(
        "你是严谨的学术文献综述作者。不得虚构文献，只能依据给定的真实来源。"
        "只能依据题名、作者、年份和来源作审慎归纳，不得把题名未支持的内容写成文献结论。"
        "只输出连续正文。",
        f"课题：{request['title']}\n补充信息：{context}\n围绕传统方案、国内外研究、主流技术、应用场景、"
        f"架构演进、现有不足和未来趋势写{status_range.minimum}-{status_range.maximum}字。"
        f"引用至少{min(len(references), 8)}篇给定文献。"
        f"{citation_instruction}"
        f"\n真实文献：\n{reference_text}",
        max_tokens=max(800, round(status_range.maximum * 1.2)),
    )
    analysis_constraints = "；".join(
        f"{field} {length.minimum}-{length.maximum}字"
        for field, length in plan.fields.items()
        if field not in {"research_purpose", "research_status_and_trends"}
    )
    source_outline = request.get("source_outline") or []
    outline_requirement = (
        "已有用户确认的论文大纲，无需生成writing_outline；研究内容与方法应围绕该大纲展开。"
        if source_outline
        else "writing_outline数组，包含1-20个与课题相符的一级章节，每项严格为"
        "{title,sections}，sections为2-5项数组，每项严格为{title,subsections}，subsections为0-4个三级标题字符串；"
        "至少一个二级标题必须包含三级标题。title与subsections中禁止自带数字、中文序号或章节编号。"
    )
    analysis = await _ask_json(
        "你是毕业设计技术方案专家。严格输出JSON对象，不要Markdown。",
        f"课题：{request['title']}\n补充信息：{context}\n生成以下字段：{analysis_constraints}；"
        f"{outline_requirement}"
        f"内容必须具体且互不重复。{citation_instruction}",
        max_tokens=max(
            2200,
            round(
                sum(
                    length.maximum
                    for field, length in plan.fields.items()
                    if field not in {"research_purpose", "research_status_and_trends"}
                )
                * 1.4
            ),
        ),
    )
    return {
        "research_purpose": purpose,
        "research_status_and_trends": status,
        "research_content": _required_text(analysis, "research_content"),
        "key_points": _required_text(analysis, "key_points"),
        "difficulties": _required_text(analysis, "difficulties"),
        "research_methods": _required_text(analysis, "research_methods"),
        "feasibility_and_innovation": _required_text(analysis, "feasibility_and_innovation"),
        "writing_outline": (
            _outline_from_source(source_outline)
            if source_outline
            else _required_outline(analysis.get("writing_outline"))
        ),
    }


def _normalize_keywords(
    value: object,
    *,
    title: str,
    source_outline: list[dict[str, Any]],
) -> list[str]:
    """规范化模型关键词，并从用户确认的大纲补足缺项。

    Args:
        value: 模型返回的关键词数组或分隔文本。
        title: 用户输入的文档题目。
        source_outline: 用户确认的结构化大纲。

    Returns:
        去重后的关键词，最多六项。
    """

    raw_items = re.split(r"[,，、;；\n]+", value) if isinstance(value, str) else value
    keywords: list[str] = []
    if isinstance(raw_items, list):
        for item in raw_items:
            if not isinstance(item, str):
                continue
            keyword = item.strip()
            if keyword and keyword not in keywords:
                keywords.append(keyword)

    if len(keywords) < 3:
        # 用户确认的题目和大纲比模型补写的未知主题更可靠。
        candidates = [title]
        for chapter in source_outline:
            if isinstance(chapter, dict):
                candidates.extend(
                    str(section.get("name", ""))
                    for section in chapter.get("sections") or []
                    if isinstance(section, dict)
                )
        for candidate in candidates:
            keyword = candidate.strip()
            if keyword and keyword not in keywords:
                keywords.append(keyword)
            if len(keywords) >= 3:
                break
    return keywords[:6]


async def generate_literature_review_content(
    request: dict[str, Any],
    references: list[ReferenceRecord],
) -> dict[str, Any]:
    """生成文献综述的结构化各部分。"""

    plan = build_length_plan("literature_review", request)
    if plan.theme is None:
        raise RuntimeError("文献综述字数预算缺少主题配置")
    context = _request_context(request)
    reference_text = _reference_text(references)
    citation_instruction = _citation_instruction(request)
    overview_fields = ("abstract", "introduction", "domestic_research", "foreign_research")
    overview_constraints = "、".join(
        f"{field}({plan.fields[field].minimum}-{plan.fields[field].maximum}字)" for field in overview_fields
    )
    overview = await _ask_json(
        "你是学术文献综述作者。严格输出JSON对象，不得虚构文献编号。"
        "只能依据题名、作者、年份和来源作审慎归纳，不得把题名未支持的内容写成文献结论。",
        f"课题：{request['title']}\n补充信息：{context}\n真实文献：\n{reference_text}\n"
        f"生成{overview_constraints}、keywords(3-6个字符串)。国内外研究必须综合比较给定资料；"
        f"{citation_instruction}",
        max_tokens=max(2200, round(sum(plan.fields[field].maximum for field in overview_fields) * 1.4)),
    )
    analysis_fields = ("method_comparison", "research_gaps", "future_trends", "conclusion")
    analysis_constraints = "、".join(
        f"{field}为{plan.fields[field].minimum}-{plan.fields[field].maximum}字" for field in analysis_fields
    )
    analysis = await _ask_json(
        "你是学术综述评审专家。严格输出JSON对象，不要Markdown，不得虚构文献。"
        "引用语句只能陈述题名和元数据能够支持的内容。",
        f"课题：{request['title']}\n补充信息：{context}\n真实文献：\n{reference_text}\n"
        f"生成themes数组{plan.theme_count}项，每项含title和content，content为"
        f"{plan.theme.minimum}-{plan.theme.maximum}字，必须比较多篇文献并包含已有做法、不同观点、"
        f"优缺点和小结；{analysis_constraints}。{citation_instruction}",
        max_tokens=max(
            2600,
            round(
                (plan.theme.maximum * plan.theme_count + sum(plan.fields[field].maximum for field in analysis_fields))
                * 1.4
            ),
        ),
    )
    analysis = await _repair_missing_text_fields(
        analysis,
        analysis_fields,
        title=str(request["title"]),
        reference_text=reference_text,
        length_plan=plan,
        request=request,
    )
    keywords = _normalize_keywords(
        overview.get("keywords"),
        title=str(request["title"]),
        source_outline=request.get("source_outline") or [],
    )
    themes = analysis.get("themes")
    if not keywords:
        raise RuntimeError("文献综述关键词结构不合法")
    if not isinstance(themes, list) or len(themes) != plan.theme_count:
        raise RuntimeError("文献综述主题结构不合法")
    return {
        "abstract": _required_text(overview, "abstract"),
        "keywords": keywords,
        "introduction": _required_text(overview, "introduction"),
        "domestic_research": _required_text(overview, "domestic_research"),
        "foreign_research": _required_text(overview, "foreign_research"),
        "themes": themes,
        "method_comparison": _required_text(analysis, "method_comparison"),
        "research_gaps": _required_text(analysis, "research_gaps"),
        "future_trends": _required_text(analysis, "future_trends"),
        "conclusion": _required_text(analysis, "conclusion"),
    }


async def generate_task_book_content(request: dict[str, Any]) -> dict[str, Any]:
    """生成任务书目标、模块任务和成果要求。"""

    numeric_requirements = _has_user_numeric_requirements(request)
    metric_instruction = (
        "用户已明确提供数值要求，只能复述这些数值，不得自行增加阈值。"
        if numeric_requirements
        else "用户未提供数值要求，禁止自行编造响应时间、并发量、覆盖率、准确率、占比或运行天数等确定性阈值；"
        "指标应写成可检查的质量要求，确需举例的数值必须明确标注为‘建议值，待导师确认’。"
    )
    result = await _ask_json(
        "你是高职和本科毕业设计任务书编制专家。严格输出JSON对象，不要填写姓名、学校、导师、签名、审核意见或日期。",
        f"课题：{request['title']}\n补充信息：{_request_context(request)}\n选题类型：{request.get('topic_type', '其他')}\n"
        "生成design_background(100-200字)、technology_stack(字符串数组)、design_goals(5-10个可验收目标)、"
        "main_indicators(4-8个可测量或可核验的主要技术/质量指标)、module_tasks(4-8项，每项含name、role、responsibilities、boundary)、"
        f"deliverable_forms(2-5项)、deliverable_requirements(2-5项)。设计目标、主要指标与模块任务不得重复。{metric_instruction}",
    )
    goals = result.get("design_goals")
    tasks = result.get("module_tasks")
    forms = result.get("deliverable_forms")
    requirements = result.get("deliverable_requirements")
    indicators = result.get("main_indicators")
    if not isinstance(goals, list) or not 5 <= len(goals) <= 10:
        raise RuntimeError("任务书设计目标数量不合法")
    if not isinstance(tasks, list) or not 4 <= len(tasks) <= 8:
        raise RuntimeError("任务书模块任务数量不合法")
    if not isinstance(forms, list) or not 2 <= len(forms) <= 5:
        raise RuntimeError("任务书成果形式数量不合法")
    if not isinstance(requirements, list) or not 2 <= len(requirements) <= 5:
        raise RuntimeError("任务书成果要求数量不合法")
    if not isinstance(indicators, list) or not 4 <= len(indicators) <= 8:
        raise RuntimeError("任务书主要指标数量不合法")
    _mark_unconfirmed_generated_metrics(request, result)
    return result


def _has_user_numeric_requirements(request: dict[str, Any]) -> bool:
    return bool(_explicit_numeric_requirements(request))


def _explicit_numeric_requirements(request: dict[str, Any]) -> list[str]:
    """只接受用户文字中的明确数值要求，不把技术版本号当作性能指标。"""

    context = request.get("research_context")
    config = request.get("thesis_config")
    details = str(context.get("additional_requirements") or "") if isinstance(context, dict) else ""
    if isinstance(config, dict):
        details = f"{details}\n{config.get('aboutmsg') or ''}"
    clauses = re.split(r"[。；;，,\n]|(?:并且|同时|以及)", details)
    metric_words = ("并发", "响应", "覆盖率", "准确率", "错误率", "占比", "时长", "阈值", "验收")
    requirements: list[str] = []
    for clause in clauses:
        if not re.search(r"\d", clause):
            continue
        positions = [clause.find(word) for word in metric_words if word in clause]
        if positions:
            requirements.append(clause[min(positions) :].strip())
    return requirements


def _mark_unconfirmed_generated_metrics(request: dict[str, Any], result: dict[str, Any]) -> None:
    """把模型自行给出的数值指标显式降级为待确认建议。"""

    confirmed_requirements = [re.sub(r"\s+", "", item) for item in _explicit_numeric_requirements(request)]
    generated_suggestion_fields: list[str] = []
    for field in ("design_goals", "deliverable_requirements", "main_indicators"):
        values = result.get(field)
        if not isinstance(values, list):
            continue
        generated_suggestion = False
        normalized: list[str] = []
        for item in values:
            value = str(item).strip()
            if re.search(r"\d|%|％|毫秒|秒内|分钟|万字", value):
                compact_value = re.sub(r"\s+", "", value)
                if not any(requirement in compact_value for requirement in confirmed_requirements):
                    generated_suggestion = True
                    if "待导师确认" not in value:
                        value = f"建议值（待导师确认）：{value}"
            normalized.append(value)
        result[field] = normalized
        if generated_suggestion:
            generated_suggestion_fields.append(field)
    result["generated_suggestion_fields"] = generated_suggestion_fields


def normalize_citation_claims(result: dict[str, Any]) -> None:
    """把题名元数据无法支持的确定性研究结论改为可核验的保守表述。"""

    raw_references = result.get("references")
    if not isinstance(raw_references, list):
        return
    references = {
        int(item["index"]): item
        for item in raw_references
        if isinstance(item, dict) and str(item.get("index") or "").isdigit()
    }
    for field in _CITATION_TEXT_FIELDS:
        value = result.get(field)
        if isinstance(value, str):
            result[field] = _normalize_citation_text(value, references)
    themes = result.get("themes")
    if isinstance(themes, list):
        for theme in themes:
            if isinstance(theme, dict) and isinstance(theme.get("content"), str):
                theme["content"] = _normalize_citation_text(str(theme["content"]), references)


def _normalize_citation_text(value: str, references: dict[int, dict[str, Any]]) -> str:
    sentences = [item for item in _SENTENCE_BOUNDARY.split(value) if item]
    normalized: list[str] = []
    conservative_indexes: set[int] = set()
    for sentence in sentences:
        indexes = [int(item) for item in re.findall(r"\[(\d+)\]", sentence)]
        if not indexes or _UNSUPPORTED_CITATION_CLAIM.search(sentence) is None:
            normalized.append(sentence)
            continue
        valid_indexes = [index for index in indexes if index in references]
        if valid_indexes:
            conservative_indexes.update(valid_indexes)
            continue
        normalized.append(sentence)
    if len(conservative_indexes) == 1:
        index = next(iter(conservative_indexes))
        title = str(references[index].get("title") or "").strip()
        normalized.append(f"文献[{index}]题名涉及《{title}》，本文仅据其题名与来源将其作为研究线索。")
    elif conservative_indexes:
        labels = "".join(f"[{index}]" for index in sorted(conservative_indexes))
        normalized.append(f"文献{labels}题名涉及本课题相关主题，本文仅据题名与来源将其作为研究线索。")
    return "".join(normalized)


def _required_outline(value: Any) -> list[dict[str, Any]]:
    """校验开题报告写作提纲，不限制为旧版固定 5-8 章。"""

    if not isinstance(value, list) or not 1 <= len(value) <= 20:
        raise RuntimeError("开题报告写作提纲结构不合法")
    normalized = [item for item in value if isinstance(item, dict) and str(item.get("title") or "").strip()]
    if len(normalized) != len(value):
        raise RuntimeError("开题报告写作提纲章节不完整")
    has_third_level = False
    for chapter in normalized:
        sections = chapter.get("sections")
        if not isinstance(sections, list) or not 2 <= len(sections) <= 5:
            raise RuntimeError("开题报告写作提纲二级标题结构不合法")
        for section in sections:
            if not isinstance(section, dict) or not str(section.get("title") or "").strip():
                raise RuntimeError("开题报告写作提纲二级标题不完整")
            subsections = section.get("subsections")
            if not isinstance(subsections, list):
                raise RuntimeError("开题报告写作提纲三级标题结构不合法")
            has_third_level = has_third_level or bool(subsections)
    if not has_third_level:
        raise RuntimeError("开题报告写作提纲缺少三级标题")
    return normalized


def _outline_from_source(source_outline: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """按用户确认的大纲重建开题报告提纲，不让模型改写章节。"""

    return [
        {
            "title": str(chapter["chapter"]),
            "sections": [
                {
                    "title": str(section["name"]),
                    "subsections": [str(item["name"]) for item in section.get("subsections") or []],
                }
                for section in chapter["sections"]
            ],
        }
        for chapter in source_outline
    ]


# 统计文献综述的可验收正文长度
def _literature_body_length(result: dict[str, Any]) -> int:
    """统计文献综述正文长度。

    Args:
        result: 结构化文献综述结果。

    Returns:
        不包含关键词和参考文献的正文非空白字符数。
    """

    total = sum(text_length(str(result.get(field) or "")) for field in LITERATURE_BODY_FIELDS)
    themes = result.get("themes")
    if isinstance(themes, list):
        total += sum(text_length(str(theme.get("content") or "")) for theme in themes if isinstance(theme, dict))
    return total


async def repair_length_constraints(
    document_type: str,
    request: dict[str, Any],
    result: dict[str, Any],
) -> None:
    """只修复超出产品字数约束的字段。"""

    plan = build_length_plan(document_type, request)
    for field, length_range in plan.fields.items():
        if field not in result:
            continue
        result[field] = await _repair_length_value(
            field,
            str(result.get(field) or "").strip(),
            length_range.minimum,
            length_range.maximum,
            request,
            result,
        )
    if document_type == "literature_review":
        if plan.theme is None:
            raise RuntimeError("文献综述字数预算缺少主题配置")
        themes = result.get("themes")
        if not isinstance(themes, list) or len(themes) != plan.theme_count:
            raise RuntimeError("文献综述主题结构不合法")
        for index, theme in enumerate(themes):
            if not isinstance(theme, dict):
                raise RuntimeError("文献综述主题结构不合法")
            theme["content"] = await _repair_length_value(
                "theme_content",
                str(theme.get("content") or "").strip(),
                plan.theme.minimum,
                plan.theme.maximum,
                request,
                result,
                field_label=f"themes[{index}].content",
            )


async def _repair_length_value(
    field: str,
    value: str,
    minimum: int,
    maximum: int,
    request: dict[str, Any],
    result: dict[str, Any],
    *,
    field_label: str | None = None,
) -> str:
    label = field_label or field
    for _ in range(3):
        length = text_length(value)
        if minimum <= length <= maximum:
            break
        citations = sorted({int(item) for item in re.findall(r"\[(\d+)\]", value)})
        citation_requirement = (
            f"必须保留并使用这些引用编号：{', '.join(f'[{item}]' for item in citations)}。"
            if citations
            else "不得增加原文不存在的引用编号。"
        )
        span = maximum - minimum
        target = minimum + (span // 3 if length > maximum else span * 2 // 3)
        paragraph_count = max(1, min(8, round(target / 250)))
        if length > maximum:
            references = result.get("references")
            cited_reference_text = ""
            if isinstance(references, list) and citations:
                cited_reference_text = "\n".join(
                    str(item.get("formatted") or "")
                    for item in references
                    if isinstance(item, dict) and item.get("index") in citations
                )
            source_instruction = (
                f"内容要求：{_FIELD_REQUIREMENTS.get(field, '保留该字段的核心事实和论证。')}\n"
                f"补充信息：{_request_context(request)}\n"
                f"可用参考文献：\n{cited_reference_text}"
            )
        else:
            source_instruction = f"原文：\n{value}"
        value = await _ask_text(
            "你是严格执行篇幅要求的学术编辑。只输出修订后的连续正文，不要标题、说明或字数统计。"
            "参考文献只提供题名与来源元数据时，只能审慎说明题名涉及的主题，不得据此编造研究发现、"
            "效果、提升幅度或作者结论。",
            f"课题：{request['title']}\n字段：{label}\n当前字符数：{length}\n"
            f"统一规划：{_request_context(request)}\n{source_instruction}\n"
            f"内容要求：{_FIELD_REQUIREMENTS.get(field, '保留该字段的核心事实和论证。')}"
            f"请修订到约{target}字，硬性范围为{minimum}-{maximum}字。"
            f"写成{paragraph_count}个自然段，每段约{max(80, target // paragraph_count)}字。"
            "字数按非空白字符统计，汉字、标点、英文字母和数字均逐字符计数；不得超出硬性范围；"
            "超长时必须重新组织语言，不得照抄原文。"
            f"{citation_requirement}",
            max_tokens=max(500, round(maximum * 1.2)),
        )
    final_length = text_length(value)
    if final_length > maximum:
        value = _trim_to_complete_sentences(value, field, minimum, maximum)
        final_length = text_length(value)
    if final_length > maximum and not re.search(r"\[\d+\]", value):
        value = _trim_to_character_limit(value, maximum)
        final_length = text_length(value)
    # 单节重写仍略短时交给后续总正文字数校验，避免为几十字重跑整份材料。
    if round(minimum * 0.8) <= final_length < minimum:
        return value
    if not minimum <= final_length <= maximum:
        raise RuntimeError(f"字段{label}字数{final_length}不在{minimum}-{maximum}范围内")
    return value


def _trim_to_character_limit(value: str, maximum: int) -> str:
    """模型多次超长且无引用时，按同一统计口径安全截到完整句号。"""

    kept: list[str] = []
    count = 0
    for char in value:
        if not char.isspace():
            if count >= maximum - 1:
                break
            count += 1
        kept.append(char)
    return "".join(kept).rstrip("，,；;：:。. ") + "。"


async def repair_reference_coverage(
    document_type: str,
    request: dict[str, Any],
    result: dict[str, Any],
    missing_references: list[ReferenceRecord],
) -> None:
    """只修复承担引用覆盖的区块，不重新生成已通过的其它字段。"""

    if not missing_references:
        return
    reference_text = _reference_text(missing_references)
    if document_type == "proposal_report":
        status_range = build_length_plan(document_type, request).fields["research_status_and_trends"]
        result["research_status_and_trends"] = await _ask_text(
            "你是严谨的开题报告文献综述作者。只输出修订后的连续正文，不要标题。",
            f"课题：{request['title']}\n统一规划：{_request_context(request)}\n"
            f"原文：\n{result.get('research_status_and_trends', '')}\n"
            f"下列真实文献尚未在正文引用：\n{reference_text}\n"
            "在保留原文主要论证和已有引用的前提下完成修订。逐篇结合标题和元数据说明与课题的关系，"
            "形成比较、评价或趋势判断，并准确使用每个给定编号；不得增加不存在的文献。"
            "只能说明题名和来源可直接支持的主题关系，不得把推测写成作者研究发现或确定性结论。"
            "每个编号必须紧跟其支撑的具体论述，每句最多2篇，禁止在段末集中罗列连续编号。"
            f"修订后的全文必须保持在{status_range.minimum}-{status_range.maximum}字。",
            max_tokens=max(800, round(status_range.maximum * 1.2)),
        )
        return
    if document_type == "literature_review":
        themes = result.get("themes")
        if not isinstance(themes, list) or not themes:
            raise RuntimeError("文献综述主题结构不合法，无法修复引用")
        supplemental = await _ask_text(
            "你是学术综述评审专家。只输出一个主题的连续正文，不要标题。",
            f"课题：{request['title']}\n统一规划：{_request_context(request)}\n"
            f"尚未引用的真实文献：\n{reference_text}\n"
            "写一个综合比较主题，必须逐篇使用给定编号，说明已有做法、不同观点、优缺点和小结。"
            "只能依据题名、作者、年份和来源做审慎归纳，不得虚构论文结论。"
            "每个给定编号都必须原样、独立出现在正文中，例如分别写[1]和[2]；禁止合并写成[1-2]、[1,2]或其他形式。"
            "每个编号必须紧跟其支撑的具体论述，每句最多2篇，禁止在段末集中罗列连续编号。",
        )
        new_theme = {"title": "补充文献的综合比较", "content": supplemental}
        planned_theme_count = build_length_plan(document_type, request).theme_count
        if len(themes) < planned_theme_count:
            themes.append(new_theme)
        else:
            previous = themes[-1]
            previous_content = str(previous.get("content") or "") if isinstance(previous, dict) else str(previous)
            themes[-1] = {
                "title": str(previous.get("title") or "综合比较") if isinstance(previous, dict) else "综合比较",
                "content": f"{previous_content}\n{supplemental}".strip(),
            }


async def _ask_text(system: str, prompt: str, *, max_tokens: int = 5000) -> str:
    llm = await create_configured_llm("fulltext", temperature=0.3, max_tokens=max_tokens)
    message = await llm.ainvoke([SystemMessage(content=system), HumanMessage(content=prompt)])
    text = _message_text(message.content)
    if not text:
        raise RuntimeError("模型未返回有效正文")
    return text


async def _ask_json(system: str, prompt: str, *, max_tokens: int = 5000) -> dict[str, Any]:
    text = await _ask_text(system, prompt, max_tokens=max_tokens)
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.IGNORECASE)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start < 0 or end <= start:
        raise RuntimeError("模型未返回JSON对象")
    try:
        data = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError as exc:
        raise RuntimeError("模型JSON解析失败") from exc
    if not isinstance(data, dict):
        raise RuntimeError("模型JSON顶层必须是对象")
    return data


async def _repair_missing_text_fields(
    data: dict[str, Any],
    required_fields: tuple[str, ...],
    *,
    title: str,
    reference_text: str,
    length_plan: MaterialLengthPlan,
    request: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """仅补生成模型偶发遗漏的文本字段，避免整次长内容调用作废。"""

    missing_fields = [field for field in required_fields if not str(data.get(field) or "").strip()]
    if not missing_fields:
        return data
    constraints = "、".join(
        f"{field}为{length_plan.fields[field].minimum}-{length_plan.fields[field].maximum}字"
        for field in missing_fields
    )
    repaired = await _ask_json(
        "你是学术综述评审专家。只补全指定的JSON文本字段，不要输出其他字段或Markdown。"
        "只能依据题名、作者、年份和来源作审慎归纳，不得虚构文献内容。",
        f"课题：{title}\n统一规划：{_request_context(request or {})}\n"
        f"真实文献：\n{reference_text}\n"
        f"上一轮缺少字段：{json.dumps(missing_fields, ensure_ascii=False)}。"
        f"请严格输出这些字段，其中{constraints}。{_citation_instruction(request or {})}",
        max_tokens=max(800, round(sum(length_plan.fields[field].maximum for field in missing_fields) * 1.8)),
    )
    merged = dict(data)
    for field in missing_fields:
        merged[field] = _required_text(repaired, field)
    return merged


def _request_context(request: dict[str, Any]) -> str:
    source_outline = request.get("source_outline") or []
    chapter_plan = [
        {
            "chapter": chapter.get("chapter"),
            "sections": [section.get("name") for section in chapter.get("sections") or []],
        }
        for chapter in source_outline
        if isinstance(chapter, dict)
    ]
    thesis_config = request.get("thesis_config") or {}
    return json.dumps(
        {
            "research_context": request.get("research_context", {}),
            "schedule_options": request.get("schedule_options", {}),
            "confirmed_outline": chapter_plan,
            "material_outline": request.get("material_outline", {}),
            "paper_context": {
                "aboutmsg": thesis_config.get("aboutmsg", ""),
            },
        },
        ensure_ascii=False,
    )


def _citation_instruction(request: dict[str, Any]) -> str:
    return "引用必须紧跟具体观点，每句最多2篇，禁止在段末集中罗列连续编号；只使用给定文献编号。"


def _reference_text(references: list[ReferenceRecord]) -> str:
    return "\n".join(item.formatted for item in references) or (
        "本次未检索到可用的真实文献。不得编造作者、题名、DOI或引用编号，也不得声称已有文献支持；"
        "研究现状与主题比较只能写成待核实的研究方向、检索计划和评价框架，不能写成已完成的文献综述。"
    )


def _message_text(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        return "".join(str(item.get("text", "")) for item in content if isinstance(item, dict)).strip()
    return str(content).strip()


def _required_text(data: dict[str, Any], key: str) -> str:
    value = str(data.get(key) or "").strip()
    if not value:
        raise RuntimeError(f"模型缺少字段: {key}")
    return value


def text_length(value: str) -> int:
    """按非空白字符统计产品字数约束。"""

    return len(re.sub(r"\s+", "", value))


def _trim_to_complete_sentences(value: str, field: str, minimum: int, maximum: int) -> str:
    """保留引用和关键主题句，在硬上限内按完整句收敛篇幅。"""

    sentences = [item.strip() for item in _SENTENCE_BOUNDARY.split(value) if item.strip()]
    if len(sentences) < 2:
        return value

    citation_indexes = {index for index, sentence in enumerate(sentences) if re.search(r"\[\d+\]", sentence)}
    topic_indexes: set[int] = set()
    for keyword_group in _FIELD_KEYWORD_GROUPS.get(field, ()):
        matched_index = next(
            (
                index
                for index, sentence in enumerate(sentences)
                if any(keyword in sentence for keyword in keyword_group)
            ),
            None,
        )
        if matched_index is not None:
            topic_indexes.add(matched_index)

    selected_indexes: set[int] = set()
    selected_length = 0
    for index in sorted(topic_indexes):
        sentence_length = text_length(sentences[index])
        if selected_length + sentence_length > maximum:
            return value
        selected_indexes.add(index)
        selected_length += sentence_length

    for index in sorted(citation_indexes - selected_indexes):
        sentence_length = text_length(sentences[index])
        if selected_length + sentence_length <= maximum:
            selected_indexes.add(index)
            selected_length += sentence_length

    target = minimum + (maximum - minimum) * 2 // 3
    for index, sentence in enumerate(sentences):
        if index in selected_indexes:
            continue
        sentence_length = text_length(sentence)
        if selected_length + sentence_length <= maximum:
            selected_indexes.add(index)
            selected_length += sentence_length
        if selected_length >= target:
            break

    if selected_length < minimum:
        return value
    return "".join(sentences[index] for index in sorted(selected_indexes))
