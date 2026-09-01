"""负责根据论文题目和写作配置生成可编辑的结构化论文大纲。"""

import json
import logging
import re
from typing import Any, cast

from langchain_core.output_parsers import StrOutputParser

from llm.client import create_configured_llm
from llm.prompts.thesis_outline_prompt import THESIS_OUTLINE_PROMPT
from schemas.thesis import OutlineChapter, OutlinePayload, OutlineSection
from services.thesis.content.quality_service import extract_confirmed_technologies, sanitize_abstract_truth
from services.thesis.generation.concurrency import text_short_slot

logger = logging.getLogger(__name__)


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
    three_level: bool,
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

    if not three_level:
        for chapter in chapters:
            for section in chapter.sections:
                section.subsections = []
        return

    sections: list[OutlineSection] = [section for chapter in chapters for section in chapter.sections]
    subsection_quotas = [0 for _ in sections]
    remaining = subsection_limit
    while remaining:
        changed = False
        for index, section in enumerate(sections):
            if subsection_quotas[index] >= min(len(section.subsections), 2):
                continue
            subsection_quotas[index] += 1
            remaining -= 1
            changed = True
            if remaining == 0:
                break
        if not changed:
            break
    for section, quota in zip(sections, subsection_quotas, strict=True):
        section.subsections = _take_edge_items(section.subsections, quota) if quota else []


def _parse_and_validate_outline(
    raw: str,
    *,
    target_word_count: int,
    three_level: bool,
    title: str = "",
    aboutmsg: str = "",
) -> dict[str, Any]:
    parsed = json.loads(_strip_json_fence(raw))
    payload = OutlinePayload.model_validate(parsed)
    _limit_outline_density(payload.outline, target_word_count=target_word_count, three_level=three_level)
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
    codetype: str,
    language: str,
    three_level: bool,
    aboutmsg: str,
    target_word_count: int,
) -> dict[str, str]:
    return {
        "codetype_instruction": (
            f"本论文涉及 {codetype} 代码实现，大纲中需包含代码/系统实现相关章节"
            if codetype and codetype != "否"
            else "本论文不要求代码实现章节。"
        ),
        "language_instruction": ("需要考虑外文文献综述内容" if language == "是" else "不强制要求外文文献综述内容"),
        "three_level_instruction": (
            (
                "短篇论文的每个二级章节必须且只生成1个三级小节，三级小节总数不得超过12个"
                if target_word_count <= 5000
                else "每个二级章节的subsections至少包含1个三级小节，避免为凑层级过度拆分"
            )
            if three_level
            else "保持常规二级章节结构，每个二级章节的 subsections 必须为空数组"
        ),
        "aboutmsg_instruction": (
            f"写作方向补充说明：{aboutmsg.strip()}" if aboutmsg and aboutmsg.strip() else "无额外写作方向补充说明"
        ),
    }


async def generate_outline(
    title: str,
    target_word_count: int = 8000,
    codetype: str = "否",
    language: str = "否",
    three_level: bool = False,
    aboutmsg: str = "",
) -> dict[str, Any]:
    """阶段①：根据论文标题生成结构化 JSON 大纲。"""

    chain = await _build_outline_chain()
    inputs = {
        "title": title,
        "target_word_count": target_word_count,
        **_build_outline_instructions(codetype, language, three_level, aboutmsg, target_word_count),
    }
    async with text_short_slot():
        result = await chain.ainvoke(inputs)
    payload = _parse_and_validate_outline(
        cast(str, result),
        target_word_count=target_word_count,
        three_level=three_level,
        title=title,
        aboutmsg=aboutmsg,
    )
    if three_level and any(
        not section["subsections"] for chapter in payload["outline"] for section in chapter["sections"]
    ):
        logger.warning("三级大纲首次生成存在空三级小节，执行一次结构重试")
        retry_inputs = dict(inputs)
        retry_inputs["three_level_instruction"] = (
            f"{inputs['three_level_instruction']}；每个二级章节都必须至少生成1个三级小节，不能返回空数组"
        )
        async with text_short_slot():
            retry_result = await chain.ainvoke(retry_inputs)
        payload = _parse_and_validate_outline(
            cast(str, retry_result),
            target_word_count=target_word_count,
            three_level=three_level,
            title=title,
            aboutmsg=aboutmsg,
        )
    if three_level and any(
        not section["subsections"] for chapter in payload["outline"] for section in chapter["sections"]
    ):
        raise RuntimeError("三级大纲生成不完整，请重试")
    return payload
