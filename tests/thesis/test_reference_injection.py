import asyncio
import tempfile
import zipfile
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from schemas.thesis_material import ReferenceRecord
from services.thesis.document.docx_builder import build_word_document
from services.thesis.generation import pipeline as thesis


# 本文件只验证生成编排，不允许进度发布访问 Redis、数据库或真实产物目录
@pytest.fixture(autouse=True)
def isolate_progress(monkeypatch: pytest.MonkeyPatch) -> None:
    """把所有生成进度写入替换为空操作，保持测试隔离。"""
    monkeypatch.setattr(thesis, "publish_progress", AsyncMock())


def test_generate_thesis_document_injects_references_before_fulltext(monkeypatch) -> None:
    calls: list[object] = []
    references_text = "[1] 物联网相关研究[J]."

    async def fake_retrieve_verified_references(title: str, outline: str, **kwargs) -> list[ReferenceRecord]:
        calls.append("references")
        return [
            ReferenceRecord(
                index=1,
                title="物联网相关研究",
                authors=["测试作者"],
                year="2025",
                formatted=references_text,
                language="zh",
            )
        ]

    async def fake_generate_fulltext(
            outline: str,
            target_word_count: int = 8000,
            references: str = "",
            **kwargs,
    ) -> str:
        calls.append(("fulltext", references, target_word_count))
        return "# 第一章 绪论\n" + "系统设计已有较多研究基础，相关方案需要结合项目材料确认。" * 380 + "[1]\n"

    async def fake_generate_abstracts(full_text: str, **kwargs) -> dict[str, str]:
        calls.append("abstracts")
        return {
            "abstract_zh": "中文摘要",
            "keywords_zh": "关键词",
            "abstract_en": "English abstract",
            "keywords_en": "keyword",
        }


    async def fake_render_all_figures(**kwargs):
        calls.append("render")
        return {}

    async def fake_to_thread(func: Callable[..., str], /, *args: Any, **kwargs: Any) -> str:
        calls.append("to_thread")
        return func(*args, **kwargs)

    def fake_build_word_document(**kwargs) -> str:
        calls.append(("build", kwargs["references"]))
        return "/tmp/fake.docx"

    monkeypatch.setattr(thesis, "_retrieve_verified_references", fake_retrieve_verified_references)
    monkeypatch.setattr(thesis, "generate_fulltext", fake_generate_fulltext)
    monkeypatch.setattr(thesis, "generate_abstracts", fake_generate_abstracts)
    monkeypatch.setattr(thesis, "extract_figure_placeholders", lambda full_text: [])
    monkeypatch.setattr(thesis, "split_by_render_method", lambda placeholders: ([], [], [], []))
    monkeypatch.setattr(thesis, "render_all_figures", fake_render_all_figures)
    monkeypatch.setattr(thesis, "build_word_document", fake_build_word_document)
    monkeypatch.setattr(thesis.asyncio, "to_thread", fake_to_thread)
    monkeypatch.setattr(
        "core.config.get_settings",
        lambda: SimpleNamespace(twelveai_api_key="", twelveai_image_model=""),
    )

    result = asyncio.run(
        thesis.generate_thesis_document(
            task_id="task123",
            title="自习室门禁管理和学习支持系统",
            outline="# 第一章 绪论",
            target_word_count=1000,
        )
    )

    assert calls.index("references") < calls.index(("fulltext", references_text, 1000))
    assert "to_thread" in calls
    assert any(isinstance(item, tuple) and item[0] == "build" and references_text in item[1] for item in calls)
    assert result.docx_path == "/tmp/fake.docx"
    assert result.fulltext_char_count > result.fulltext_word_count > 0
    assert result.truncation_warning is False
    assert result.result_data["reference_count"] == 1


def test_generate_thesis_document_does_not_hide_internal_reference_errors(monkeypatch) -> None:
    calls: list[object] = []

    async def fake_retrieve_verified_references(title: str, outline: str, **kwargs) -> list[ReferenceRecord]:
        raise RuntimeError("serpapi down")

    async def fake_generate_fulltext(
            outline: str,
            target_word_count: int = 8000,
            references: str = "",
            **kwargs,
    ) -> str:
        calls.append(("fulltext", references))
        return "# 第一章 绪论\n正文。\n"

    async def fake_generate_abstracts(full_text: str, **kwargs) -> dict[str, str]:
        return {
            "abstract_zh": "",
            "keywords_zh": "",
            "abstract_en": "",
            "keywords_en": "",
        }


    async def fake_render_all_figures(**kwargs):
        return {}

    monkeypatch.setattr(thesis, "_retrieve_verified_references", fake_retrieve_verified_references)
    monkeypatch.setattr(thesis, "generate_fulltext", fake_generate_fulltext)
    monkeypatch.setattr(thesis, "generate_abstracts", fake_generate_abstracts)
    monkeypatch.setattr(thesis, "extract_figure_placeholders", lambda full_text: [])
    monkeypatch.setattr(thesis, "split_by_render_method", lambda placeholders: ([], [], [], []))
    monkeypatch.setattr(thesis, "render_all_figures", fake_render_all_figures)
    monkeypatch.setattr(thesis, "build_word_document", lambda **kwargs: "/tmp/fake.docx")
    monkeypatch.setattr(
        "core.config.get_settings",
        lambda: SimpleNamespace(twelveai_api_key="", twelveai_image_model=""),
    )

    with pytest.raises(RuntimeError, match="serpapi down"):
        asyncio.run(
            thesis.generate_thesis_document(
                task_id="task123",
                title="自习室门禁管理和学习支持系统",
                outline="# 第一章 绪论",
            )
        )

    assert calls == []


# 文献降级必须贯穿正文、摘要、Word 和任务结果，不能在后置校验再次失败
@pytest.mark.parametrize("available_count", [0, 2])
async def test_shortage_pipeline_builds_docx_with_actual_citations(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, available_count: int,
) -> None:
    """使用真实 Word 构建器验证零文献和不足目标时的交付内容。"""
    records = [
        ReferenceRecord(
            index=index, title=f"测试课题研究{index}", authors=["测试作者"], year="2025",
            language="zh", source="测试期刊", pages="1-5",
            formatted=f"[{index}]测试作者.测试课题研究{index}[J].测试期刊,2025(1):1-5.",
        )
        for index in range(1, available_count + 1)
    ]
    retrieve = AsyncMock(return_value=records)
    fulltext = AsyncMock(return_value=(
        "# 1 绪论\n" + "本课题的研究方向需要结合后续资料审慎确认。" * 80
        + "待核实的研究方向[1][2][99][1-99]。\n# 参考文献\n[99]模型自行编造的来源。"
    ))
    monkeypatch.setattr(thesis, "_retrieve_verified_references", retrieve)
    monkeypatch.setattr(thesis, "generate_fulltext", fulltext)
    monkeypatch.setattr(thesis, "generate_abstracts", AsyncMock(return_value={"abstract_zh": "摘要[99]。"}))
    monkeypatch.setattr(thesis, "render_all_figures", AsyncMock(return_value={}))
    monkeypatch.setattr("core.config.get_settings", lambda: SimpleNamespace(thesis_output_root=str(tmp_path)))

    result = await thesis.generate_thesis_document(
        task_id="isolated-shortage", title="测试课题", outline="# 1 绪论",
        target_word_count=1000, chinese_reference_count=17, english_reference_count=8, allow_ai_images=False,
    )

    assert Path(result.docx_path).is_file()
    assert result.result_data["reference_count"] == available_count
    assert result.result_data["quality_warnings"]
    assert result.result_data["citation_integrity"] == ("closed" if records else "no_references")
    retrieve.assert_awaited_once_with("测试课题", "# 1 绪论", chinese_reference_count=17, english_reference_count=8)
    with zipfile.ZipFile(result.docx_path) as archive:
        xml = archive.read("word/document.xml").decode()
    assert "[99]" not in xml
    assert "[1-99]" not in xml
    assert "模型自行编造" not in xml
    assert "文献检索提示" in xml or "待补充参考文献" in xml
    if not records:
        assert "未检索到可用的真实文献" in xml
        assert "[1]" not in xml
        assert "不得编造" in fulltext.call_args.kwargs["writing_requirements"]
    else:
        assert "[1]" in xml and "[2]" in xml
        assert "目标25篇，实际可用2篇" in xml


def test_docx_builder_renders_citations_as_superscript() -> None:
    out = Path(tempfile.mktemp(suffix=".docx"))
    try:
        build_word_document(
            title="测试论文",
            full_text="# 第一章 绪论\n相关研究已经较为成熟[1][2]。\n",
            output_path=str(out),
            abstract_zh="中文摘要",
            keywords_zh="关键词",
            abstract_en="English abstract",
            keywords_en="keyword",
            acknowledgment="感谢。",
            references="[1] 文献一。\n[2] 文献二。",
            placeholders=[],
            image_paths={},
        )

        with zipfile.ZipFile(out) as zf:
            document_xml = zf.read("word/document.xml").decode("utf-8")

        assert "[1]" in document_xml
        assert "[2]" in document_xml
        assert document_xml.count('w:vertAlign w:val="superscript"') >= 2
    finally:
        out.unlink(missing_ok=True)
