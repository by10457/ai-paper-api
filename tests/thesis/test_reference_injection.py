import asyncio
import tempfile
import zipfile
from pathlib import Path
from types import SimpleNamespace

from services import thesis
from services.thesis.docx_builder import build_word_document


def test_generate_thesis_document_injects_references_before_fulltext(monkeypatch) -> None:
    calls: list[object] = []
    references_text = "[1] 物联网相关研究[J]."

    async def fake_generate_references(title: str, outline: str, **kwargs) -> str:
        calls.append("references")
        return references_text

    async def fake_generate_fulltext(
            outline: str,
            target_word_count: int = 8000,
            references: str = "",
            **kwargs,
    ) -> str:
        calls.append(("fulltext", references, target_word_count))
        return "# 第一章 绪论\n系统设计已有较多研究基础[1]。\n"

    async def fake_generate_abstracts(full_text: str) -> dict[str, str]:
        calls.append("abstracts")
        return {
            "abstract_zh": "中文摘要",
            "keywords_zh": "关键词",
            "abstract_en": "English abstract",
            "keywords_en": "keyword",
        }

    async def fake_generate_acknowledgment(title: str, advisor: str) -> str:
        calls.append("ack")
        return "感谢。"

    async def fake_render_all_figures(**kwargs):
        calls.append("render")
        return {}

    def fake_build_word_document(**kwargs) -> str:
        calls.append(("build", kwargs["references"]))
        return "/tmp/fake.docx"

    monkeypatch.setattr(thesis, "generate_references", fake_generate_references)
    monkeypatch.setattr(thesis, "generate_fulltext", fake_generate_fulltext)
    monkeypatch.setattr(thesis, "generate_abstracts", fake_generate_abstracts)
    monkeypatch.setattr(thesis, "generate_acknowledgment", fake_generate_acknowledgment)
    monkeypatch.setattr(thesis, "extract_figure_placeholders", lambda full_text: [])
    monkeypatch.setattr(thesis, "split_by_render_method", lambda placeholders: ([], [], [], []))
    monkeypatch.setattr(thesis, "render_all_figures", fake_render_all_figures)
    monkeypatch.setattr(thesis, "build_word_document", fake_build_word_document)
    monkeypatch.setattr(
        "core.config.get_settings",
        lambda: SimpleNamespace(twelveai_api_key="", twelveai_image_model=""),
    )

    result = asyncio.run(
        thesis.generate_thesis_document(
            task_id="task123",
            title="自习室门禁管理和学习支持系统",
            outline="# 第一章 绪论",
            target_word_count=9000,
        )
    )

    assert calls[0] == "references"
    assert calls[1] == ("fulltext", references_text, 9000)
    assert ("build", references_text) in calls
    assert result.docx_path == "/tmp/fake.docx"


def test_generate_thesis_document_degrades_when_references_fail(monkeypatch) -> None:
    calls: list[object] = []

    async def fake_generate_references(title: str, outline: str, **kwargs) -> str:
        raise RuntimeError("serpapi down")

    async def fake_generate_fulltext(
            outline: str,
            target_word_count: int = 8000,
            references: str = "",
            **kwargs,
    ) -> str:
        calls.append(("fulltext", references))
        return "# 第一章 绪论\n正文。\n"

    async def fake_generate_abstracts(full_text: str) -> dict[str, str]:
        return {
            "abstract_zh": "",
            "keywords_zh": "",
            "abstract_en": "",
            "keywords_en": "",
        }

    async def fake_generate_acknowledgment(title: str, advisor: str) -> str:
        return ""

    async def fake_render_all_figures(**kwargs):
        return {}

    monkeypatch.setattr(thesis, "generate_references", fake_generate_references)
    monkeypatch.setattr(thesis, "generate_fulltext", fake_generate_fulltext)
    monkeypatch.setattr(thesis, "generate_abstracts", fake_generate_abstracts)
    monkeypatch.setattr(thesis, "generate_acknowledgment", fake_generate_acknowledgment)
    monkeypatch.setattr(thesis, "extract_figure_placeholders", lambda full_text: [])
    monkeypatch.setattr(thesis, "split_by_render_method", lambda placeholders: ([], [], [], []))
    monkeypatch.setattr(thesis, "render_all_figures", fake_render_all_figures)
    monkeypatch.setattr(thesis, "build_word_document", lambda **kwargs: "/tmp/fake.docx")
    monkeypatch.setattr(
        "core.config.get_settings",
        lambda: SimpleNamespace(twelveai_api_key="", twelveai_image_model=""),
    )

    asyncio.run(
        thesis.generate_thesis_document(
            task_id="task123",
            title="自习室门禁管理和学习支持系统",
            outline="# 第一章 绪论",
        )
    )

    assert calls == [("fulltext", "")]


def test_docx_builder_renders_citations_as_superscript() -> None:
    out = Path(tempfile.mktemp(suffix=".docx"))
    try:
        build_word_document(
            title="测试论文",
            full_text="# 第一章 绪论\n相关研究已经较为成熟[1][2]。\n",
            output_path=str(out),
            author="测试用户",
            advisor="导师",
            degree_type="学士",
            major="软件工程",
            school="计算机学院",
            year_month="2026年5月",
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
