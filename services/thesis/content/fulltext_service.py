from functools import lru_cache
from typing import Any, cast

from langchain_core.output_parsers import StrOutputParser

from core.config import get_settings
from llm.client import create_llm
from llm.prompts.thesis_fulltext_prompt import THESIS_FULLTEXT_PROMPT


@lru_cache
def _build_fulltext_chain() -> Any:
    settings = get_settings()
    llm = create_llm(
        model=settings.thesis_fulltext_model,
        # deepseek-reasoner 不支持 temperature；create_llm 内部会自动过滤。
        max_tokens=32768,
    )
    return THESIS_FULLTEXT_PROMPT | llm | StrOutputParser()


async def generate_fulltext(
    outline: str,
    target_word_count: int = 8000,
    references: str = "",
    codetype: str = "否",
) -> str:
    """阶段②：根据大纲生成论文正文（含图片占位符）。"""

    chain = _build_fulltext_chain()

    # 经验修正：LLM 实际输出字数约为 prompt 中指定字数的 1.7 倍，
    # 因此将传给 prompt 的字数除以 1.7，使最终输出贴近用户期望。
    correction_factor = 1.7
    prompt_word_count = int(target_word_count / correction_factor)
    prompt_word_count_max = int((target_word_count + 1000) / correction_factor)

    result = cast(
        str,
        await chain.ainvoke(
            {
                "outline": outline,
                "target_word_count": prompt_word_count,
                "target_word_count_max": prompt_word_count_max,
                "references": references,
                "codetype_instruction": (
                    f"本论文涉及 {codetype} 代码实现，请在系统设计与实现章节中嵌入核心代码片段"
                    if codetype and codetype != "否"
                    else ""
                ),
            }
        ),
    )
    return result.strip()
