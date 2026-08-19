"""负责根据论文大纲、参考文献和写作要求生成论文正文内容。"""

import logging
import re
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import BaseMessage

from llm.client import create_configured_llm
from llm.prompts.thesis_fulltext_prompt import THESIS_FULLTEXT_PROMPT
from schemas.thesis import FIGURE_BLOCK_PATTERN
from services.thesis.generation.concurrency import text_long_slot

logger = logging.getLogger(__name__)

# 单次正文调用最多处理三个一级章节，避免长输出在后半篇被模型截断。
MAX_CHAPTERS_PER_CALL = 3
# 历史实测模型正文约为提示目标的 1.7 倍，先校准全文目标再按章节分批。
PROMPT_WORD_COUNT_CORRECTION_FACTOR = 1.7
# 识别正文和大纲中的一级 Markdown 标题，同时兼容模型省略井号后空格的情况。
CHAPTER_HEADING_PATTERN = re.compile(r"^#(?!#)[ \t]*(?P<title>\S.*)$")
# 去除模型标题中的章节编号后比较业务标题。
CHAPTER_NUMBER_PREFIX_PATTERN = re.compile(r"^\s*(?:第\s*[一二三四五六七八九十百零\d]+\s*章|\d+)(?:[\s、:：.\-]+)?")
# 模型供应商常见的输出长度终止原因。
TOKEN_LIMIT_FINISH_REASONS = {"length", "max_tokens", "max_output_tokens"}
# Word/WPS 对中文通常逐字计数，对英文和数字按连续词计数。
CJK_CHARACTER_PATTERN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
ASCII_WORD_PATTERN = re.compile(r"[A-Za-z0-9]+(?:[._+-][A-Za-z0-9]+)*")


@dataclass(frozen=True)
class GeneratedChunk:
    """单批正文文本及模型结束原因。"""

    text: str
    finish_reason: str = ""


def count_visible_words(full_text: str) -> int:
    """估算最终 Word 正文中的可见字数。

    中文字符逐字计数，连续英文或数字按一个词计数；图表占位 JSON 和
    Markdown 代码围栏不会写入最终正文，因此不参与统计。

    Args:
        full_text: 模型生成的 Markdown 正文。

    Returns:
        接近 Word/WPS 口径的正文可见字数。
    """

    visible_text = FIGURE_BLOCK_PATTERN.sub("", full_text)
    visible_lines = [line for line in visible_text.splitlines() if not line.strip().startswith("```")]
    normalized = "\n".join(visible_lines)
    return len(CJK_CHARACTER_PATTERN.findall(normalized)) + len(ASCII_WORD_PATTERN.findall(normalized))


def _lines_outside_code_fences(text: str) -> list[str]:
    """返回 Markdown 代码围栏之外的行。"""

    lines: list[str] = []
    is_code_block = False
    for line in text.splitlines():
        if line.strip().startswith("```"):
            is_code_block = not is_code_block
            continue
        if not is_code_block:
            lines.append(line)
    return lines


async def _build_fulltext_chain() -> Any:
    """创建保留模型响应元数据的正文调用链。

    Returns:
        正文提示词与模型组成的 LangChain 调用链。
    """

    llm = await create_configured_llm(
        "fulltext",
        # 部分推理模型不支持 temperature，模型客户端内部会自动过滤。
        max_tokens=32768,
    )
    return THESIS_FULLTEXT_PROMPT | llm


# 将 Markdown 大纲按一级章节切分
def _split_outline_chapters(outline: str) -> list[str]:
    """按一级标题切分论文大纲。

    Args:
        outline: 带 Markdown 标题的用户确认大纲。

    Returns:
        按原顺序排列的一级章节大纲；无法识别一级标题时保留完整输入。
    """

    normalized = outline.strip()
    if not normalized:
        return []
    lines = normalized.splitlines()
    starts = [index for index, line in enumerate(lines) if CHAPTER_HEADING_PATTERN.match(line.strip())]
    if not starts:
        return [normalized]

    chapters: list[str] = []
    for position, start in enumerate(starts):
        end = starts[position + 1] if position + 1 < len(starts) else len(lines)
        chapter = "\n".join(lines[start:end]).strip()
        if chapter:
            chapters.append(chapter)
    return chapters


# 提取单章大纲的一级标题
def _outline_chapter_title(chapter_outline: str) -> str:
    """提取章节大纲中的一级标题。

    Args:
        chapter_outline: 单个一级章节的大纲 Markdown。

    Returns:
        一级标题；没有可识别标题时返回空字符串。
    """

    for line in chapter_outline.splitlines():
        match = CHAPTER_HEADING_PATTERN.match(line.strip())
        if match:
            return match.group("title").strip()
    return ""


# 归一化章节标题，允许模型在编号格式上存在轻微差异
def _normalize_chapter_title(title: str) -> str:
    """归一化章节标题用于完整性比较。

    Args:
        title: 大纲或模型正文中的一级标题。

    Returns:
        去除章节编号、空白和常见分隔符后的标题键。
    """

    without_number = CHAPTER_NUMBER_PREFIX_PATTERN.sub("", title.strip(), count=1)
    return re.sub(r"[\s、:：.\-]+", "", without_number).casefold()


# 找出模型正文没有覆盖的大纲章节
def _missing_chapters(chapter_outlines: list[str], text: str) -> list[str]:
    """比较大纲与正文一级标题并返回缺失章节。

    Args:
        chapter_outlines: 本次要求生成的章节大纲。
        text: 模型返回的正文。

    Returns:
        未在正文一级标题中出现的章节大纲。
    """

    generated_titles = {
        _normalize_chapter_title(match.group("title"))
        for line in _lines_outside_code_fences(text)
        if (match := CHAPTER_HEADING_PATTERN.match(line.strip()))
    }
    return [
        chapter
        for chapter in chapter_outlines
        if (title := _outline_chapter_title(chapter)) and _normalize_chapter_title(title) not in generated_titles
    ]


# 从字符串或模型消息中提取正文和结束原因
def _extract_generated_chunk(result: object) -> GeneratedChunk:
    """提取模型正文及 finish reason。

    Args:
        result: LangChain 返回的字符串或消息对象。

    Returns:
        归一化后的正文片段和结束原因。
    """

    if isinstance(result, str):
        return GeneratedChunk(text=result.strip())
    if not isinstance(result, BaseMessage):
        raise RuntimeError("正文模型返回了不支持的数据类型")

    content = result.content
    if isinstance(content, str):
        text = content
    else:
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        text = "\n".join(parts)
    metadata = result.response_metadata if isinstance(result.response_metadata, dict) else {}
    finish_reason = str(metadata.get("finish_reason") or metadata.get("stop_reason") or "").strip()
    return GeneratedChunk(text=text.strip(), finish_reason=finish_reason)


# 判断模型是否因为输出长度限制结束
def _is_token_limited(finish_reason: str) -> bool:
    """判断模型结束原因是否为输出长度限制。

    Args:
        finish_reason: 模型供应商返回的结束原因。

    Returns:
        达到 token 或输出长度上限时返回 True。
    """

    return finish_reason.casefold() in TOKEN_LIMIT_FINISH_REASONS


# 调用一次正文模型并保留可观测元数据
async def _invoke_fulltext(
    chain: Any,
    outline: str,
    target_word_count: int,
    references: str,
    codetype: str,
) -> GeneratedChunk:
    """生成一个大纲批次对应的正文。

    Args:
        chain: 已创建的正文模型调用链。
        outline: 本批次章节大纲。
        target_word_count: 本批次目标字数。
        references: 可引用的参考文献文本。
        codetype: 代码语言类型。

    Returns:
        模型正文和结束原因。
    """

    target_word_count_max = target_word_count + max(300, int(target_word_count * 0.15))
    async with text_long_slot():
        result = await chain.ainvoke(
            {
                "outline": outline,
                "target_word_count": target_word_count,
                "target_word_count_max": target_word_count_max,
                "references": references,
                "codetype_instruction": (
                    f"本论文涉及 {codetype} 代码实现，请在系统设计与实现章节中嵌入核心代码片段"
                    if codetype and codetype != "否"
                    else ""
                ),
            }
        )
    return _extract_generated_chunk(result)


# 异常批次退化为逐章生成，避免继续交付缺章正文
async def _regenerate_chapters(
    chain: Any,
    chapter_outlines: list[str],
    target_word_count: int,
    references: str,
    codetype: str,
) -> list[str]:
    """逐章重新生成并验证异常批次。

    Args:
        chain: 已创建的正文模型调用链。
        chapter_outlines: 需要恢复的章节大纲。
        target_word_count: 每个章节的目标字数。
        references: 可引用的参考文献文本。
        codetype: 代码语言类型。

    Returns:
        按大纲顺序排列的完整章节正文。

    Raises:
        RuntimeError: 单章仍被截断或缺少对应一级标题。
    """

    results: list[str] = []
    for chapter_outline in chapter_outlines:
        generated = await _invoke_fulltext(
            chain,
            chapter_outline,
            target_word_count,
            references,
            codetype,
        )
        missing = _missing_chapters([chapter_outline], generated.text)
        if _is_token_limited(generated.finish_reason) or missing:
            chapter_title = _outline_chapter_title(chapter_outline) or "未知章节"
            raise RuntimeError(f"正文生成章节不完整：{chapter_title}")
        results.append(generated.text)
    return results


async def generate_fulltext(
    outline: str,
    target_word_count: int = 8000,
    references: str = "",
    codetype: str = "否",
) -> str:
    """阶段②：分批生成正文并确保所有一级章节完整。

    Args:
        outline: 用户确认后的 Markdown 大纲。
        target_word_count: 全文目标字数。
        references: 可引用的参考文献文本。
        codetype: 代码语言类型，不生成代码时为“否”。

    Returns:
        按大纲顺序拼接的完整论文正文。

    Raises:
        RuntimeError: 大纲为空，或模型重试后仍存在缺章/截断。
    """

    chain = await _build_fulltext_chain()
    chapter_outlines = _split_outline_chapters(outline)
    if not chapter_outlines:
        raise RuntimeError("大纲不能为空")

    chapter_count = len(chapter_outlines)
    prompt_target_word_count = round(target_word_count / PROMPT_WORD_COUNT_CORRECTION_FACTOR)
    per_chapter_target = max(round(prompt_target_word_count / chapter_count), 300)
    logger.info(
        "正文目标字数校准：user_target=%d, prompt_target=%d, factor=%.1f, chapters=%d",
        target_word_count,
        prompt_target_word_count,
        PROMPT_WORD_COUNT_CORRECTION_FACTOR,
        chapter_count,
    )
    generated_parts: list[str] = []
    for start in range(0, chapter_count, MAX_CHAPTERS_PER_CALL):
        batch = chapter_outlines[start : start + MAX_CHAPTERS_PER_CALL]
        batch_target = max(
            round(prompt_target_word_count * len(batch) / chapter_count),
            per_chapter_target * len(batch),
        )
        generated = await _invoke_fulltext(
            chain,
            "\n\n".join(batch),
            batch_target,
            references,
            codetype,
        )
        missing = _missing_chapters(batch, generated.text)
        if _is_token_limited(generated.finish_reason) or missing:
            logger.warning(
                "正文批次不完整，改为逐章重生成：start=%d, chapter_count=%d, finish_reason=%s, missing=%s",
                start + 1,
                len(batch),
                generated.finish_reason or "unknown",
                [_outline_chapter_title(item) for item in missing],
            )
            generated_parts.extend(
                await _regenerate_chapters(
                    chain,
                    batch,
                    per_chapter_target,
                    references,
                    codetype,
                )
            )
        else:
            generated_parts.append(generated.text)

    full_text = "\n\n".join(generated_parts).strip()
    missing = _missing_chapters(chapter_outlines, full_text)
    if missing:
        missing_titles = "、".join(_outline_chapter_title(item) or "未知章节" for item in missing)
        raise RuntimeError(f"正文生成章节不完整，缺少：{missing_titles}")
    return full_text
