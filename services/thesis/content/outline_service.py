"""负责根据论文题目和写作配置生成可编辑的结构化论文大纲。"""

import json
import re
from typing import Any, cast

from langchain_core.output_parsers import StrOutputParser

from llm.client import create_configured_llm
from llm.prompts.thesis_outline_prompt import THESIS_OUTLINE_PROMPT
from schemas.thesis import OutlineChapter, OutlinePayload, OutlineSection
from services.thesis.content.quality_service import extract_confirmed_technologies, sanitize_abstract_truth
from services.thesis.generation.concurrency import text_short_slot


async def _build_outline_chain() -> Any:
    llm = await create_configured_llm(
        "outline",
        temperature=0.4,
        max_tokens=8192,
    )
    return THESIS_OUTLINE_PROMPT | llm | StrOutputParser()


def _strip_json_fence(text: str) -> str:
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned).strip()
    return cleaned


def _take_edge_items[T](items: list[T], limit: int) -> list[T]:
    if len(items) <= limit:
        return items
    if limit <= 1:
        return items[:1]
    return [*items[: limit - 1], items[-1]]


def _outline_density_limits(target_word_count: int) -> tuple[int, int]:
    if target_word_count <= 5000:
        return 12, 12
    if target_word_count <= 8000:
        return 18, 18
    if target_word_count <= 12000:
        return 24, 24
    return 32, 32


def _limit_outline_density(
    chapters: list[OutlineChapter],
    *,
    target_word_count: int,
) -> None:
    """按目标正文篇幅限制标题密度，避免短文被标题和固定结构挤满。"""

    section_limit, subsection_limit = _outline_density_limits(target_word_count)
    quotas = [1 for _ in chapters]
    remaining = max(section_limit - len(chapters), 0)
    while remaining:
        changed = False
        for index, chapter in enumerate(chapters):
            if quotas[index] >= len(chapter.sections):
                continue
            quotas[index] += 1
            remaining -= 1
            changed = True
            if remaining == 0:
                break
        if not changed:
            break
    for chapter, quota in zip(chapters, quotas, strict=True):
        chapter.sections = _take_edge_items(chapter.sections, quota)

    sections: list[OutlineSection] = [section for chapter in chapters for section in chapter.sections]
    # 按完整的小节组分配预算，避免把两个子主题裁剪成单独一个三级标题。
    remaining = subsection_limit
    for section in sections:
        desired = min(len(section.subsections), 3)
        if desired < 2 or remaining < 2:
            section.subsections = []
            continue
        quota = min(desired, remaining)
        section.subsections = _take_edge_items(section.subsections, quota)
        remaining -= quota


def _parse_and_validate_outline(
    raw: str,
    *,
    target_word_count: int,
    title: str = "",
    aboutmsg: str = "",
) -> dict[str, Any]:
    parsed = json.loads(_strip_json_fence(raw))
    payload = OutlinePayload.model_validate(parsed)
    _limit_outline_density(payload.outline, target_word_count=target_word_count)
    sanitized, _ = sanitize_abstract_truth(
        {"abstract_zh": payload.abstract},
        writing_requirements=aboutmsg,
        confirmed_technologies=extract_confirmed_technologies(f"{title} {aboutmsg}"),
    )
    payload.abstract = sanitized["abstract_zh"]
    confirmed_technologies = extract_confirmed_technologies(f"{title} {aboutmsg}")
    for chapter in payload.outline:
        for section in chapter.sections:
            section_data, _ = sanitize_abstract_truth(
                {"abstract_zh": section.abstract},
                writing_requirements=aboutmsg,
                confirmed_technologies=confirmed_technologies,
                include_disclaimer=False,
            )
            section.abstract = section_data["abstract_zh"]
            for subsection in section.subsections:
                subsection_data, _ = sanitize_abstract_truth(
                    {"abstract_zh": subsection.abstract},
                    writing_requirements=aboutmsg,
                    confirmed_technologies=confirmed_technologies,
                    include_disclaimer=False,
                )
                subsection.abstract = subsection_data["abstract_zh"]
    return payload.model_dump()


def _build_outline_instructions(
    chinese_reference_count: int,
    english_reference_count: int,
    aboutmsg: str,
) -> dict[str, str]:
    return {
        "code_instruction": "依据题目与研究内容判断是否需要代码或系统实现章节；不得为非编程课题强行添加代码。",
        "reference_instruction": (
            f"参考文献规划目标：中文{chinese_reference_count}篇、英文{english_reference_count}篇；"
            "按研究需要规划相关研究章节，不编造具体文献。"
        ),
        "aboutmsg_instruction": (
            f"写作方向补充说明：{aboutmsg.strip()}" if aboutmsg and aboutmsg.strip() else "无额外写作方向补充说明"
        ),
    }


async def generate_outline(
    title: str,
    target_word_count: int = 8000,
    chinese_reference_count: int = 25,
    english_reference_count: int = 0,
    aboutmsg: str = "",
) -> dict[str, Any]:
    """阶段①：根据论文标题生成结构化 JSON 大纲。"""

    chain = await _build_outline_chain()
    inputs = {
        "title": title,
        "target_word_count": target_word_count,
        **_build_outline_instructions(chinese_reference_count, english_reference_count, aboutmsg),
    }
    async with text_short_slot():
        result = await chain.ainvoke(inputs)
    payload = _parse_and_validate_outline(
        cast(str, result),
        target_word_count=target_word_count,
        title=title,
        aboutmsg=aboutmsg,
    )
    return payload
