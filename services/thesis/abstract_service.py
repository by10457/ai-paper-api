import logging

from langchain_core.output_parsers import StrOutputParser

from core.config import get_settings
from llm.client import create_llm
from llm.prompts.thesis_abstract_prompt import (
    ABSTRACT_COMBINED_PROMPT,
    ACKNOWLEDGMENT_PROMPT,
)

logger = logging.getLogger(__name__)


def _parse_body_and_keywords(raw: str, kw_prefixes: tuple[str, ...]) -> tuple[str, str]:
    """从模型输出中拆分正文与关键词。"""
    lines = raw.strip().splitlines()
    keywords = ""
    body_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        matched = False
        for prefix in kw_prefixes:
            if stripped.startswith(prefix):
                keywords = stripped[len(prefix) :].strip()
                matched = True
                break
        if not matched:
            body_lines.append(line)
    return "\n".join(body_lines).strip(), keywords


def _parse_combined_abstract(raw: str) -> dict[str, str]:
    """解析单次 LLM 输出中的中英文摘要及关键词。"""
    zh_section = ""
    en_section = ""

    en_marker = "===英文摘要==="
    zh_marker = "===中文摘要==="

    if en_marker in raw:
        parts = raw.split(en_marker, 1)
        zh_section = parts[0].replace(zh_marker, "").strip()
        en_section = parts[1].strip()
    else:
        # 兜底：没有英文分隔符时，整段视为中文摘要
        zh_section = raw.replace(zh_marker, "").strip()

    abstract_zh, keywords_zh = _parse_body_and_keywords(zh_section, ("【关键词】", "关键词：", "关键词:"))
    abstract_en, keywords_en = _parse_body_and_keywords(en_section, ("【KEY WORDS】", "Keywords:", "KEY WORDS:"))

    return {
        "abstract_zh": abstract_zh,
        "keywords_zh": keywords_zh,
        "abstract_en": abstract_en,
        "keywords_en": keywords_en,
    }


async def generate_abstracts(full_text: str) -> dict[str, str]:
    """单次 LLM 调用同时生成中英文摘要，英文为中文的忠实翻译。"""
    settings = get_settings()
    llm = create_llm(
        model=settings.thesis_outline_model,
        temperature=0.3,
        max_tokens=2048,
    )

    chain = ABSTRACT_COMBINED_PROMPT | llm | StrOutputParser()
    raw = await chain.ainvoke({"text_sample": full_text})

    result = _parse_combined_abstract(raw)
    logger.info(
        "摘要生成完成: zh=%d字 en=%d字",
        len(result["abstract_zh"]),
        len(result["abstract_en"]),
    )
    return result


async def generate_acknowledgment(title: str, advisor: str) -> str:
    """生成致谢正文。"""
    settings = get_settings()
    llm = create_llm(
        model=settings.thesis_outline_model,
        temperature=0.7,
        max_tokens=1024,
    )
    chain = ACKNOWLEDGMENT_PROMPT | llm | StrOutputParser()
    result = await chain.ainvoke({"title": title, "advisor": advisor})
    return result.strip()
