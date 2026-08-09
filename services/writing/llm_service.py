"""三类学术材料的结构化大模型生成。"""

from __future__ import annotations

import json
import re
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from llm.client import create_configured_llm
from schemas.writing import ReferenceRecord

WRITING_LENGTH_CONSTRAINTS: dict[str, dict[str, tuple[int, int]]] = {
    "proposal_report": {
        "research_purpose": (700, 1000),
        "research_status_and_trends": (1400, 2000),
        "key_points": (300, 500),
        "difficulties": (300, 500),
        "research_methods": (400, 600),
    },
    "literature_review": {
        "abstract": (200, 300),
        "introduction": (400, 600),
        "domestic_research": (600, 800),
        "foreign_research": (600, 800),
        "method_comparison": (500, 700),
        "research_gaps": (350, 500),
        "future_trends": (350, 500),
        "conclusion": (300, 450),
    },
    "task_book": {"design_background": (100, 200)},
}

LITERATURE_THEME_LENGTH = (500, 700)
LITERATURE_BODY_LENGTH = (5500, 7500)

_FIELD_REQUIREMENTS = {
    "research_purpose": "涵盖行业背景、现实问题、技术背景、研究必要性、应用价值和研究目标。",
    "research_status_and_trends": "涵盖传统方案、国内外研究、主流技术、应用场景、架构演进、现有不足和未来趋势，并形成比较评价。",
    "key_points": "说明系统架构、核心功能、数据设计和关键业务。",
    "difficulties": "说明性能、并发、数据一致性、安全、交互或算法难点。",
    "research_methods": "说明技术路线、框架、数据库、接口、测试和问题解决手段。",
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
    "key_points": (("架构",), ("功能",), ("数据",), ("业务",)),
    "difficulties": (("性能", "并发"), ("一致性",), ("安全",), ("交互", "算法")),
    "research_methods": (("技术路线",), ("框架",), ("数据库",), ("接口",), ("测试",)),
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


async def generate_proposal_content(
    request: dict[str, Any],
    references: list[ReferenceRecord],
) -> dict[str, Any]:
    """分三次生成开题报告主体，避免单次长输出丢失区块。"""

    context = _request_context(request)
    reference_text = _reference_text(references)
    purpose = await _ask_text(
        "你是本科毕业设计开题报告写作专家。只输出连续正文，不要标题。",
        f"课题：{request['title']}\n补充信息：{context}\n写700-1000字研究目的，必须包括行业背景、现实问题、技术背景、必要性、应用价值和研究目标。可引用[1]-[2]。\n真实文献：\n{reference_text}",
    )
    status = await _ask_text(
        "你是严谨的学术文献综述作者。不得虚构文献，只能使用给定编号。只输出连续正文。",
        f"课题：{request['title']}\n补充信息：{context}\n围绕传统方案、国内外研究、主流技术、应用场景、架构演进、现有不足和未来趋势写1400-2000字。引用至少8篇给定文献。\n真实文献：\n{reference_text}",
    )
    analysis = await _ask_json(
        "你是毕业设计技术方案专家。严格输出JSON对象，不要Markdown。",
        f"课题：{request['title']}\n补充信息：{context}\n生成以下字段：key_points 300-500字；difficulties 300-500字；research_methods 400-600字。内容必须具体且互不重复。JSON键只能是key_points、difficulties、research_methods。",
    )
    return {
        "research_purpose": purpose,
        "research_status_and_trends": status,
        "key_points": _required_text(analysis, "key_points"),
        "difficulties": _required_text(analysis, "difficulties"),
        "research_methods": _required_text(analysis, "research_methods"),
    }


async def generate_literature_review_content(
    request: dict[str, Any],
    references: list[ReferenceRecord],
) -> dict[str, Any]:
    """生成文献综述的结构化各部分。"""

    context = _request_context(request)
    reference_text = _reference_text(references)
    overview = await _ask_json(
        "你是学术文献综述作者。严格输出JSON对象，不得虚构文献编号。",
        f"课题：{request['title']}\n补充信息：{context}\n真实文献：\n{reference_text}\n"
        "生成abstract(200-300字)、keywords(3-6个字符串)、introduction(400-600字)、"
        "domestic_research(600-800字)、foreign_research(600-800字)。国内外研究必须综合比较并引用给定编号。",
    )
    analysis = await _ask_json(
        "你是学术综述评审专家。严格输出JSON对象，不要Markdown，不得虚构文献。",
        f"课题：{request['title']}\n真实文献：\n{reference_text}\n"
        "生成themes数组5项，每项含title和content，content为500-700字，必须比较多篇文献并包含已有做法、不同观点、优缺点和小结；"
        "method_comparison为500-700字、research_gaps为350-500字、future_trends为350-500字、conclusion为300-450字。",
    )
    keywords = overview.get("keywords")
    themes = analysis.get("themes")
    if not isinstance(keywords, list) or not 3 <= len(keywords) <= 6:
        raise RuntimeError("文献综述关键词结构不合法")
    if not isinstance(themes, list) or not 3 <= len(themes) <= 6:
        raise RuntimeError("文献综述主题结构不合法")
    return {
        "abstract": _required_text(overview, "abstract"),
        "keywords": [str(item).strip() for item in keywords],
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

    result = await _ask_json(
        "你是高职和本科毕业设计任务书编制专家。严格输出JSON对象，不要填写姓名、学校、导师、签名、审核意见或日期。",
        f"课题：{request['title']}\n补充信息：{_request_context(request)}\n选题类型：{request.get('topic_type', '其他')}\n生成design_background(100-200字)、technology_stack(字符串数组)、design_goals(5-10个可验收目标)、module_tasks(4-8项，每项含name、role、responsibilities、boundary)、deliverable_forms(2-5项)、deliverable_requirements(2-5项)。设计目标与模块任务不得重复。",
    )
    goals = result.get("design_goals")
    tasks = result.get("module_tasks")
    forms = result.get("deliverable_forms")
    requirements = result.get("deliverable_requirements")
    if not isinstance(goals, list) or not 5 <= len(goals) <= 10:
        raise RuntimeError("任务书设计目标数量不合法")
    if not isinstance(tasks, list) or not 4 <= len(tasks) <= 8:
        raise RuntimeError("任务书模块任务数量不合法")
    if not isinstance(forms, list) or not 2 <= len(forms) <= 5:
        raise RuntimeError("任务书成果形式数量不合法")
    if not isinstance(requirements, list) or not 2 <= len(requirements) <= 5:
        raise RuntimeError("任务书成果要求数量不合法")
    return result


async def repair_length_constraints(
    document_type: str,
    request: dict[str, Any],
    result: dict[str, Any],
) -> None:
    """只修复超出产品字数约束的字段。"""

    constraints = WRITING_LENGTH_CONSTRAINTS.get(document_type, {})
    for field, (minimum, maximum) in constraints.items():
        result[field] = await _repair_length_value(
            field,
            str(result.get(field) or "").strip(),
            minimum,
            maximum,
            request,
            result,
        )
    if document_type == "literature_review":
        themes = result.get("themes")
        if not isinstance(themes, list):
            raise RuntimeError("文献综述主题结构不合法")
        for index, theme in enumerate(themes):
            if not isinstance(theme, dict):
                raise RuntimeError("文献综述主题结构不合法")
            theme["content"] = await _repair_length_value(
                "theme_content",
                str(theme.get("content") or "").strip(),
                *LITERATURE_THEME_LENGTH,
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
            "你是严格执行篇幅要求的学术编辑。只输出修订后的连续正文，不要标题、说明或字数统计。",
            f"课题：{request['title']}\n字段：{label}\n当前字符数：{length}\n{source_instruction}\n"
            f"内容要求：{_FIELD_REQUIREMENTS.get(field, '保留该字段的核心事实和论证。')}"
            f"请修订到约{target}字，硬性范围为{minimum}-{maximum}字。"
            f"写成{paragraph_count}个自然段，每段约{max(80, target // paragraph_count)}字。"
            "字数按中文字符、汉字标点和英文单词共同计算，不得超出硬性范围；超长时必须重新组织语言，不得照抄原文。"
            f"{citation_requirement}",
            max_tokens=max(400, int(maximum * 0.9)),
        )
    final_length = text_length(value)
    if final_length > maximum:
        value = _trim_to_complete_sentences(value, field, minimum, maximum)
        final_length = text_length(value)
    if not minimum <= final_length <= maximum:
        raise RuntimeError(f"字段{label}字数{final_length}不在{minimum}-{maximum}范围内")
    return value


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
        result["research_status_and_trends"] = await _ask_text(
            "你是严谨的开题报告文献综述作者。只输出修订后的连续正文，不要标题。",
            f"课题：{request['title']}\n原文：\n{result.get('research_status_and_trends', '')}\n"
            f"下列真实文献尚未在正文引用：\n{reference_text}\n"
            "在保留原文主要论证和已有引用的前提下完成修订。逐篇结合标题和元数据说明与课题的关系，"
            "形成比较、评价或趋势判断，并准确使用每个给定编号；不得增加不存在的文献。"
            "修订后的全文必须保持在1400-2000字。",
            max_tokens=3000,
        )
        return
    if document_type == "literature_review":
        themes = result.get("themes")
        if not isinstance(themes, list) or not themes:
            raise RuntimeError("文献综述主题结构不合法，无法修复引用")
        supplemental = await _ask_text(
            "你是学术综述评审专家。只输出一个主题的连续正文，不要标题。",
            f"课题：{request['title']}\n尚未引用的真实文献：\n{reference_text}\n"
            "写一个综合比较主题，必须逐篇使用给定编号，说明已有做法、不同观点、优缺点和小结。"
            "只能依据题名、作者、年份和来源做审慎归纳，不得虚构论文结论。"
            "每个给定编号都必须原样、独立出现在正文中，例如分别写[1]和[2]；禁止合并写成[1-2]、[1,2]或其他形式。",
        )
        new_theme = {"title": "补充文献的综合比较", "content": supplemental}
        if len(themes) < 6:
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


async def _ask_json(system: str, prompt: str) -> dict[str, Any]:
    text = await _ask_text(system, prompt)
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


def _request_context(request: dict[str, Any]) -> str:
    return json.dumps(
        {
            "student_profile": request.get("student_profile", {}),
            "research_context": request.get("research_context", {}),
            "schedule_options": request.get("schedule_options", {}),
        },
        ensure_ascii=False,
    )


def _reference_text(references: list[ReferenceRecord]) -> str:
    return "\n".join(item.formatted for item in references)


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

    citation_indexes = {
        index for index, sentence in enumerate(sentences) if re.search(r"\[\d+\]", sentence)
    }
    topic_indexes: set[int] = set()
    for keyword_group in _FIELD_KEYWORD_GROUPS.get(field, ()):
        matched_index = next(
            (index for index, sentence in enumerate(sentences) if any(keyword in sentence for keyword in keyword_group)),
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
