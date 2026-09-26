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
LONG_PAPER_CHAPTERS_PER_CALL = 1
LONG_PAPER_BATCH_THRESHOLD = 20000
# 当前正文模型在 4000-10000 字分批生成时的实测扩写倍率约为 1.35-1.55。
# 使用早期 1.7 倍经验会让提示目标稳定偏低，并在最终 90% 字数校验处造成整单失败。
# 取略保守的 1.2，偏长结果仍由质量层无损收敛到目标区间。
SHORT_PAPER_CORRECTION_FACTOR = 1.2
LONG_PAPER_CORRECTION_FACTOR = 0.8
CORRECTION_TRANSITION_START = 10000
CORRECTION_TRANSITION_END = 30000
SHORT_PAPER_MIN_CHAPTER_TARGET = 180
DEFAULT_MIN_CHAPTER_TARGET = 300
# 识别正文和大纲中的一级 Markdown 标题，同时兼容模型省略井号后空格的情况。
CHAPTER_HEADING_PATTERN = re.compile(r"^#(?!#)[ \t]*(?P<title>\S.*)$")
# 识别任意 Markdown 标题，用于约束模型不得突破用户确认大纲的最大层级。
MARKDOWN_HEADING_PATTERN = re.compile(r"^(?P<marks>#{1,6})[ \t]+(?P<title>\S.*)$")
# 去除阿拉伯数字及“一、”等中文列表序号；重复序号需逐层剥离。
CHAPTER_NUMBER_PREFIX_PATTERN = re.compile(
    r"^\s*(?:(?:第\s*[一二三四五六七八九十百零\d]+\s*章|\d+)(?:[\s、:：.\-]+)?|"
    r"[一二三四五六七八九十百零]+[、:：.\-]\s*)"
)
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


# 按目标篇幅计算提示字数折算，避免把短篇经验直接套到三万字长文
def _prompt_word_count_correction_factor(target_word_count: int) -> float:
    """返回正文提示目标的动态折算系数。

    Args:
        target_word_count: 用户要求的正文目标字数。

    Returns:
        短篇使用历史扩写系数，长篇逐步降低到实测长文系数。
    """

    if target_word_count <= CORRECTION_TRANSITION_START:
        return SHORT_PAPER_CORRECTION_FACTOR
    if target_word_count >= CORRECTION_TRANSITION_END:
        return LONG_PAPER_CORRECTION_FACTOR
    progress = (target_word_count - CORRECTION_TRANSITION_START) / (
        CORRECTION_TRANSITION_END - CORRECTION_TRANSITION_START
    )
    return SHORT_PAPER_CORRECTION_FACTOR - progress * (SHORT_PAPER_CORRECTION_FACTOR - LONG_PAPER_CORRECTION_FACTOR)


# 长篇改为逐章调用，避免多章共享单次输出上限导致总字数稳定不足
def _chapters_per_call(target_word_count: int) -> int:
    """返回单次正文模型调用包含的一级章节数。

    Args:
        target_word_count: 用户要求的正文目标字数。

    Returns:
        两万字及以上逐章生成，其余论文保持三章一批。
    """

    if target_word_count >= LONG_PAPER_BATCH_THRESHOLD:
        return LONG_PAPER_CHAPTERS_PER_CALL
    return MAX_CHAPTERS_PER_CALL


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


def _outline_max_heading_depth(outline: str) -> int:
    """返回用户确认大纲包含的最大 Markdown 标题层级。"""

    depths = [
        len(match.group("marks"))
        for line in _lines_outside_code_fences(outline)
        if (match := MARKDOWN_HEADING_PATTERN.match(line.strip()))
    ]
    return max(depths, default=1)


def _constrain_heading_depth(text: str, outline: str) -> str:
    """把超出确认大纲层级的模型自增标题还原为普通正文。"""

    max_depth = _outline_max_heading_depth(outline)
    normalized_lines: list[str] = []
    is_code_block = False
    for line in text.splitlines():
        if line.strip().startswith("```"):
            is_code_block = not is_code_block
            normalized_lines.append(line)
            continue
        match = None if is_code_block else MARKDOWN_HEADING_PATTERN.match(line.strip())
        if match is not None and len(match.group("marks")) > max_depth:
            normalized_lines.append(match.group("title").strip())
        else:
            normalized_lines.append(line)
    return "\n".join(normalized_lines).strip()


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

    without_number = title.strip()
    while (stripped := CHAPTER_NUMBER_PREFIX_PATTERN.sub("", without_number, count=1)) != without_number:
        without_number = stripped
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


# 按顺序核对一级标题，防止模型添加同号或额外章节却通过“包含”检查。
def _chapter_sequence_matches(chapter_outlines: list[str], text: str) -> bool:
    """判断正文一级标题是否与本批大纲完全一致。

    Args:
        chapter_outlines: 本批次的一级章节大纲。
        text: 模型生成或清理后的正文。

    Returns:
        标题数量、语义和顺序均一致时返回 True。
    """
    expected = [_normalize_chapter_title(_outline_chapter_title(chapter)) for chapter in chapter_outlines]
    actual = [
        _normalize_chapter_title(match.group("title"))
        for line in _lines_outside_code_fences(text)
        if (match := CHAPTER_HEADING_PATTERN.match(line.strip()))
    ]
    return actual == expected


# 正文经事实清理后再次核对章节，防止后处理破坏 Markdown 结构而静默交付缺章文档。
def validate_fulltext_chapters(outline: str, full_text: str) -> None:
    """验证最终正文仍覆盖用户确认大纲的每个一级章节。

    Args:
        outline: 用户确认的 Markdown 大纲。
        full_text: 即将写入 Word 的最终 Markdown 正文。

    Raises:
        RuntimeError: 最终正文缺少一级章节。
    """
    missing = _missing_chapters(_split_outline_chapters(outline), full_text)
    if missing:
        missing_titles = "、".join(_outline_chapter_title(item) or "未知章节" for item in missing)
        raise RuntimeError(f"正文生成章节不完整，缺少：{missing_titles}")
    if not _chapter_sequence_matches(_split_outline_chapters(outline), full_text):
        raise RuntimeError("正文生成章节结构与大纲不符")


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
    writing_requirements: str,
    confirmed_technologies: str,
    evidence_instruction: str,
) -> GeneratedChunk:
    """生成一个大纲批次对应的正文。

    Args:
        chain: 已创建的正文模型调用链。
        outline: 本批次章节大纲。
        target_word_count: 本批次目标字数。
        references: 可引用的参考文献文本。

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
                "writing_requirements": writing_requirements or "未提供补充材料",
                "confirmed_technologies": confirmed_technologies or "未确认具体技术栈",
                "evidence_instruction": evidence_instruction,
            }
        )
    return _extract_generated_chunk(result)


# 异常批次退化为逐章生成，避免继续交付缺章正文
async def _regenerate_chapters(
    chain: Any,
    chapter_outlines: list[str],
    target_word_count: int,
    references: str,
    writing_requirements: str,
    confirmed_technologies: str,
    evidence_instruction: str,
) -> list[str]:
    """逐章重新生成并验证异常批次。

    Args:
        chain: 已创建的正文模型调用链。
        chapter_outlines: 需要恢复的章节大纲。
        target_word_count: 每个章节的目标字数。
        references: 可引用的参考文献文本。

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
            writing_requirements,
            confirmed_technologies,
            evidence_instruction,
        )
        missing = _missing_chapters([chapter_outline], generated.text)
        if (
            _is_token_limited(generated.finish_reason)
            or missing
            or not _chapter_sequence_matches([chapter_outline], generated.text)
        ):
            chapter_title = _outline_chapter_title(chapter_outline) or "未知章节"
            raise RuntimeError(f"正文生成章节不完整：{chapter_title}")
        results.append(generated.text)
    return results


async def generate_fulltext(
    outline: str,
    target_word_count: int = 8000,
    references: str = "",
    writing_requirements: str = "",
    confirmed_technologies: str = "",
    evidence_instruction: str = "未提供真实测试数据，禁止输出实测结论或数据图。",
) -> str:
    """阶段②：分批生成正文并确保所有一级章节完整。

    Args:
        outline: 用户确认后的 Markdown 大纲。
        target_word_count: 全文目标字数。
        references: 可引用的参考文献文本。

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
    correction_factor = _prompt_word_count_correction_factor(target_word_count)
    prompt_target_word_count = round(target_word_count / correction_factor)
    minimum_chapter_target = SHORT_PAPER_MIN_CHAPTER_TARGET if target_word_count <= 5000 else DEFAULT_MIN_CHAPTER_TARGET
    per_chapter_target = max(round(prompt_target_word_count / chapter_count), minimum_chapter_target)
    chapters_per_call = _chapters_per_call(target_word_count)
    logger.info(
        "正文目标字数校准：user_target=%d, prompt_target=%d, factor=%.1f, chapters=%d",
        target_word_count,
        prompt_target_word_count,
        correction_factor,
        chapter_count,
    )
    generated_parts: list[str] = []
    for start in range(0, chapter_count, chapters_per_call):
        batch = chapter_outlines[start : start + chapters_per_call]
        batch_target = max(
            round(prompt_target_word_count * len(batch) / chapter_count),
            per_chapter_target * len(batch),
        )
        generated = await _invoke_fulltext(
            chain,
            "\n\n".join(batch),
            batch_target,
            references,
            writing_requirements,
            confirmed_technologies,
            evidence_instruction,
        )
        missing = _missing_chapters(batch, generated.text)
        if (
            _is_token_limited(generated.finish_reason)
            or missing
            or not _chapter_sequence_matches(batch, generated.text)
        ):
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
                    writing_requirements,
                    confirmed_technologies,
                    evidence_instruction,
                )
            )
        else:
            generated_parts.append(generated.text)

    full_text = _constrain_heading_depth("\n\n".join(generated_parts), outline)
    validate_fulltext_chapters(outline, full_text)
    return full_text
