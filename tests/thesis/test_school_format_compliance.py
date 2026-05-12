import tempfile
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from services.thesis.docx_builder import build_word_document

NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}

SAMPLE_BODY = """\
# 1 绪论
## 1.1 研究背景
正文段落。
表 1.1 测试表
| 字段 | 含义 |
| --- | --- |
| 用户 | 使用系统的人 |
# 2 系统设计
## 2.1 总体设计
正文段落。
"""


@pytest.fixture(scope="module")
def generated_docx() -> Path:
    out = Path(tempfile.mktemp(suffix=".docx"))
    build_word_document(
        title="校途系统设计与实现",
        full_text=SAMPLE_BODY,
        output_path=str(out),
        author="测试用户",
        advisor="导师",
        degree_type="学士",
        major="软件工程",
        school="信息技术学院",
        year_month="2026年5月",
        student_id="20260001",
        student_class="软件工程1班",
        abstract_zh="中文摘要内容。",
        keywords_zh="校途；论文",
        abstract_en="English abstract content.",
        keywords_en="school route; thesis",
        acknowledgment="感谢老师。",
        references="[1] 作者.题名[J].期刊,2024,1(1):1-5.",
        placeholders=[{"index": 0, "caption": "图 1.1 测试图", "render_method": "fallback"}],
        image_paths={0: None},
    )
    yield out
    out.unlink(missing_ok=True)


@pytest.fixture(scope="module")
def document_xml(generated_docx: Path) -> str:
    with zipfile.ZipFile(generated_docx) as zf:
        return zf.read("word/document.xml").decode("utf-8")


def _section_properties(document_xml: str):
    root = ET.fromstring(document_xml)
    return root.findall(".//w:sectPr", NS)


def test_school_page_margins_and_header_footer_distance(document_xml: str) -> None:
    assert 'w:top="1701"' in document_xml or 'w:top="1700"' in document_xml
    assert 'w:bottom="1531"' in document_xml or 'w:bottom="1530"' in document_xml
    assert document_xml.count('w:left="1701"') >= 1 or document_xml.count('w:left="1700"') >= 1
    assert document_xml.count('w:right="1701"') >= 1 or document_xml.count('w:right="1700"') >= 1
    assert 'w:header="1134"' in document_xml
    assert 'w:footer="1134"' in document_xml


def test_front_matter_text_format_markers(document_xml: str) -> None:
    assert "摘    要" in document_xml
    assert "ABSTRACT" in document_xml
    assert "【关键词】" in document_xml
    assert "【KEY WORDS】" in document_xml
    assert "本科生毕业论文（设计）诚信承诺书" in document_xml
    assert "本科生毕业论文（设计）版权使用授权书" in document_xml


def test_no_legacy_chapter_prefix_or_failure_caption(document_xml: str) -> None:
    assert "第一章" not in document_xml
    assert "第二章" not in document_xml
    assert "图片生成失败" not in document_xml


def test_toc_contains_back_matter(document_xml: str) -> None:
    assert "参考文献" in document_xml
    assert "致    谢" in document_xml
    assert "PAGEREF _toc_" in document_xml


def test_table_uses_three_line_style_and_five_point_font(document_xml: str) -> None:
    assert "TableGrid" not in document_xml
    assert 'w:val="nil"' in document_xml
    assert 'w:val="21"' in document_xml


def test_references_use_18pt_spacing_and_hanging_indent(document_xml: str) -> None:
    assert 'w:line="360"' in document_xml
    assert 'w:hanging="454"' in document_xml or 'w:hanging="453"' in document_xml


def test_section_page_numbering_rules(document_xml: str) -> None:
    sect_prs = _section_properties(document_xml)
    assert len(sect_prs) >= 5

    first_pg_num = sect_prs[0].find("w:pgNumType", NS)
    assert first_pg_num is None

    roman_start = [
        pg for sect in sect_prs
        if (pg := sect.find("w:pgNumType", NS)) is not None
        and pg.get(f"{{{NS['w']}}}fmt") == "upperRoman"
        and pg.get(f"{{{NS['w']}}}start") == "1"
    ]
    assert len(roman_start) == 1

    roman_continue = [
        pg for sect in sect_prs
        if (pg := sect.find("w:pgNumType", NS)) is not None
        and pg.get(f"{{{NS['w']}}}fmt") == "upperRoman"
        and pg.get(f"{{{NS['w']}}}start") is None
    ]
    assert len(roman_continue) >= 2

    body_start = [
        pg for sect in sect_prs
        if (pg := sect.find("w:pgNumType", NS)) is not None
        and pg.get(f"{{{NS['w']}}}fmt") is None
        and pg.get(f"{{{NS['w']}}}start") == "1"
    ]
    assert body_start
