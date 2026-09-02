"""论文正文分批生成与章节完整性测试。"""

from collections.abc import Iterator
from typing import Any
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage

from services.thesis.content import fulltext_service


class FakeFulltextChain:
    """按测试预设返回正文片段的模型链。"""

    def __init__(self, responses: Iterator[str | AIMessage]) -> None:
        self.responses = responses
        self.inputs: list[dict[str, Any]] = []

    # 记录每批正文请求并返回预设结果
    async def ainvoke(self, inputs: dict[str, Any]) -> str | AIMessage:
        """返回下一条预设模型结果。

        Args:
            inputs: 正文模型调用参数。

        Returns:
            预设的文本或模型消息。
        """

        self.inputs.append(inputs)
        return next(self.responses)


# 构造带编号的结构化 Markdown 大纲
def _outline(chapter_count: int) -> str:
    """构造测试大纲。

    Args:
        chapter_count: 一级章节数量。

    Returns:
        可供正文服务解析的 Markdown 大纲。
    """

    return "\n\n".join(
        f"# {index} 第{index}部分\n## {index}.1 核心内容"
        for index in range(1, chapter_count + 1)
    )


# 构造完整覆盖指定大纲批次的模型正文
def _body_for_outline(outline: str) -> str:
    """把批次大纲转换为最小完整正文。

    Args:
        outline: 单批 Markdown 大纲。

    Returns:
        保留所有标题的正文。
    """

    lines: list[str] = []
    for line in outline.splitlines():
        lines.append(line)
        if line.startswith("## "):
            lines.append("本节正文内容。")
    return "\n".join(lines)


def test_count_visible_words_excludes_figure_metadata() -> None:
    """有效字数应统计可见中英文内容，但忽略图表占位元数据。"""

    full_text = """\
# 1 绪论
中文正文 AI paper 2026。
<<FIGURE>>
{"type": "mermaid", "caption": "不应计入的图标题"}
<</FIGURE>>
```python
# 数据加载
print("hello")
```
"""

    assert fulltext_service.count_visible_words(full_text) == 16


def test_missing_chapters_ignores_headings_inside_code_fences() -> None:
    """代码注释不能冒充模型应生成的一级章节。"""

    chapters = fulltext_service._split_outline_chapters(_outline(2))
    generated = """\
# 1 第1部分
正文。
```python
# 2 第2部分
```
"""

    assert fulltext_service._missing_chapters(chapters, generated) == [chapters[1]]


def test_constrain_heading_depth_strips_model_added_third_level_heading() -> None:
    """关闭三级大纲时，模型自行添加的三级标题只能作为普通正文保留。"""

    outline = "# 1 绪论\n## 1.1 研究背景"
    generated = "# 1 绪论\n## 1.1 研究背景\n### 1.1.1 模型自行拆分\n正文内容。"

    result = fulltext_service._constrain_heading_depth(generated, outline)

    assert "### 1.1.1 模型自行拆分" not in result
    assert "1.1.1 模型自行拆分" in result


# 七章大纲应按三章一批生成，并完整保留全部章节
async def test_generate_fulltext_batches_seven_chapters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证七章正文不会依赖一次超长模型输出。

    Args:
        monkeypatch: pytest 替换工具。
    """

    outline = _outline(7)
    batches = fulltext_service._split_outline_chapters(outline)
    responses = iter(
        _body_for_outline("\n\n".join(batch))
        for batch in (batches[:3], batches[3:6], batches[6:])
    )
    chain = FakeFulltextChain(responses)
    monkeypatch.setattr(fulltext_service, "_build_fulltext_chain", AsyncMock(return_value=chain))

    result = await fulltext_service.generate_fulltext(outline, target_word_count=7000)

    assert len(chain.inputs) == 3
    assert [item["target_word_count"] for item in chain.inputs] == [2500, 2500, 833]
    assert [item["target_word_count_max"] for item in chain.inputs] == [2875, 2875, 1133]
    for index in range(1, 8):
        assert f"# {index} 第{index}部分" in result


async def test_short_paper_does_not_force_three_hundred_words_per_chapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """短篇多章节正文应按总目标分配，避免章节下限反向推高篇幅。"""

    outline = _outline(7)
    batches = fulltext_service._split_outline_chapters(outline)
    chain = FakeFulltextChain(iter(_body_for_outline("\n\n".join(batch)) for batch in (batches[:3], batches[3:6], batches[6:])))
    monkeypatch.setattr(fulltext_service, "_build_fulltext_chain", AsyncMock(return_value=chain))

    await fulltext_service.generate_fulltext(outline, target_word_count=3000)

    assert [item["target_word_count"] for item in chain.inputs] == [1071, 1071, 357]


# 三万字长篇不得继续套用短篇 1.7 倍扩写系数
async def test_long_paper_uses_lower_prompt_correction_factor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证长篇提示目标接近用户目标，避免正文稳定低于最低验收线。

    Args:
        monkeypatch: pytest 替换工具。
    """

    outline = _outline(7)
    batches = fulltext_service._split_outline_chapters(outline)
    chain = FakeFulltextChain(iter(_body_for_outline(batch) for batch in batches))
    monkeypatch.setattr(fulltext_service, "_build_fulltext_chain", AsyncMock(return_value=chain))

    await fulltext_service.generate_fulltext(outline, target_word_count=30000)

    assert fulltext_service._prompt_word_count_correction_factor(3000) == 1.2
    assert fulltext_service._prompt_word_count_correction_factor(30000) == 0.8
    assert fulltext_service._chapters_per_call(3000) == 3
    assert fulltext_service._chapters_per_call(30000) == 1
    assert [item["target_word_count"] for item in chain.inputs] == [5357] * 7


# 批次漏章时应丢弃残缺结果并逐章重生成
async def test_generate_fulltext_regenerates_incomplete_batch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证模型漏掉后半章节时会进行逐章恢复。

    Args:
        monkeypatch: pytest 替换工具。
    """

    responses: Iterator[str | AIMessage] = iter(
        [
            "# 1 第1部分\n正文。",
            "# 1 第1部分\n## 1.1 核心内容\n完整正文。",
            "# 2 第2部分\n## 2.1 核心内容\n完整正文。",
        ]
    )
    chain = FakeFulltextChain(responses)
    monkeypatch.setattr(fulltext_service, "_build_fulltext_chain", AsyncMock(return_value=chain))

    result = await fulltext_service.generate_fulltext(_outline(2), target_word_count=2000)

    assert len(chain.inputs) == 3
    assert result.count("# 1 第1部分") == 1
    assert result.count("# 2 第2部分") == 1


# 模型明确报告 token 截断时应逐章重生成当前批次
async def test_generate_fulltext_regenerates_token_limited_batch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证达到模型输出上限时不会直接交付批次结果。

    Args:
        monkeypatch: pytest 替换工具。
    """

    responses: Iterator[str | AIMessage] = iter(
        [
            AIMessage(
                content="# 1 第1部分\n正文。\n# 2 第2部分\n未完成正文",
                response_metadata={"finish_reason": "length"},
            ),
            "# 1 第1部分\n## 1.1 核心内容\n完整正文。",
            "# 2 第2部分\n## 2.1 核心内容\n完整正文。",
        ]
    )
    chain = FakeFulltextChain(responses)
    monkeypatch.setattr(fulltext_service, "_build_fulltext_chain", AsyncMock(return_value=chain))

    result = await fulltext_service.generate_fulltext(_outline(2), target_word_count=2000)

    assert len(chain.inputs) == 3
    assert "完整正文" in result
    assert "未完成正文" not in result


# 逐章恢复后仍缺章时必须失败，避免交付残缺论文
async def test_generate_fulltext_rejects_persistently_missing_chapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证无法恢复的缺章结果会终止生成。

    Args:
        monkeypatch: pytest 替换工具。
    """

    chain = FakeFulltextChain(iter(["# 1 第1部分\n正文。", "普通正文。", "普通正文."]))
    monkeypatch.setattr(fulltext_service, "_build_fulltext_chain", AsyncMock(return_value=chain))

    with pytest.raises(RuntimeError, match="章节不完整"):
        await fulltext_service.generate_fulltext(_outline(2), target_word_count=2000)
