import json
import re
from functools import lru_cache
from typing import Any, cast

from langchain_core.output_parsers import StrOutputParser

from core.config import get_settings
from llm.client import create_llm
from llm.prompts.thesis_outline_prompt import THESIS_OUTLINE_PROMPT
from schemas.thesis import OutlinePayload


@lru_cache
def _build_outline_chain() -> Any:
    settings = get_settings()
    llm = create_llm(
        model=settings.thesis_outline_model,
        temperature=0.4,
        max_tokens=2048,
    )
    return THESIS_OUTLINE_PROMPT | llm | StrOutputParser()


def _strip_json_fence(text: str) -> str:
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned).strip()
    return cleaned


def _parse_and_validate_outline(raw: str) -> dict[str, Any]:
    parsed = json.loads(_strip_json_fence(raw))
    payload = OutlinePayload.model_validate(parsed)
    return payload.model_dump()


def _build_outline_instructions(
    codetype: str,
    language: str,
    three_level: bool,
    aboutmsg: str,
) -> dict[str, str]:
    return {
        "codetype_instruction": (
            f"本论文涉及 {codetype} 代码实现，大纲中需包含代码/系统实现相关章节"
            if codetype and codetype != "否"
            else "本论文不要求代码实现章节。"
        ),
        "language_instruction": ("需要考虑外文文献综述内容" if language == "是" else "不强制要求外文文献综述内容"),
        "three_level_instruction": (
            "每个二级章节下需要拆分出 2-3 个三级小节" if three_level else "保持常规二级章节结构即可"
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

    chain = _build_outline_chain()
    result = await chain.ainvoke(
        {
            "title": title,
            "target_word_count": target_word_count,
            **_build_outline_instructions(codetype, language, three_level, aboutmsg),
        }
    )
    return _parse_and_validate_outline(cast(str, result))
