"""Tests for the visible TOC + PAGEREF implementation in docx_builder.

Each test generates a minimal DOCX via build_word_document(), unzips it,
and inspects the raw word/document.xml to verify the OOXML structure.
"""

import re
import tempfile
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from services.thesis.docx_builder import (
    _pre_scan_headings,
    build_word_document,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

# Minimal body text covering all 3 heading levels
SAMPLE_BODY = """\
# 1 绪论
## 1.1 研究背景
正文段落。
## 1.2 研究意义
正文段落。
# 2 相关技术
## 2.1 Spring Boot 框架概述
### 2.1.1 核心特性
正文段落。
## 2.2 MySQL 数据库
正文段落。
# 3 系统设计
## 3.1 总体架构设计
正文段落。
"""

SAMPLE_TITLE = "基于 Spring Boot 的校园管理系统"
NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}


def _build_sample_docx() -> Path:
    """Generate a minimal DOCX and return its path."""
    out = Path(tempfile.mktemp(suffix=".docx"))
    build_word_document(
        title=SAMPLE_TITLE,
        full_text=SAMPLE_BODY,
        output_path=str(out),
        author="测试用户",
        advisor="导师",
        degree_type="学士",
        major="软件工程",
        school="计算机学院",
        year_month="2026年5月",
        abstract_zh="中文摘要内容。",
        keywords_zh="关键词1；关键词2",
        abstract_en="English abstract content.",
        keywords_en="keyword1; keyword2",
        acknowledgment="感谢所有帮助过我的人。",
        references="[1] 某参考文献。",
        placeholders=[],
        image_paths={},
    )
    return out


def _read_document_xml(docx_path: Path) -> str:
    """Extract word/document.xml as a UTF-8 string."""
    with zipfile.ZipFile(docx_path) as zf:
        return zf.read("word/document.xml").decode("utf-8")


@pytest.fixture(scope="module")
def generated_docx() -> Path:
    """Module-scoped fixture: generate once, reuse across tests."""
    path = _build_sample_docx()
    yield path
    path.unlink(missing_ok=True)


@pytest.fixture(scope="module")
def document_xml(generated_docx) -> str:
    return _read_document_xml(generated_docx)


# ---------------------------------------------------------------------------
# 1. No legacy TOC field code
# ---------------------------------------------------------------------------

class TestNoLegacyTOC:
    """Ensure the old TOC \\o field and hint text are gone."""

    def test_no_toc_field_instruction(self, document_xml):
        """document.xml must NOT contain 'TOC \\o' field instruction."""
        assert 'TOC \\o' not in document_xml
        assert "TOC \\\\o" not in document_xml

    def test_no_hint_text(self, document_xml):
        """The old '目录生成完毕' prompt text must be absent."""
        assert "目录生成完毕" not in document_xml
        assert "按 F9 更新" not in document_xml


# ---------------------------------------------------------------------------
# 2. Bookmarks on body headings
# ---------------------------------------------------------------------------

class TestBookmarks:
    """Bookmarks _toc_0, _toc_1, ... must exist on body headings."""

    def test_bookmarks_present(self, document_xml):
        tree = ET.fromstring(document_xml)
        bookmarks = tree.findall(".//w:bookmarkStart", NS)
        toc_bookmarks = [
            bm.get(f"{{{NS['w']}}}name")
            for bm in bookmarks
            if (bm.get(f"{{{NS['w']}}}name") or "").startswith("_toc_")
        ]
        assert len(toc_bookmarks) > 0, "No _toc_* bookmarks found"

    def test_bookmark_count_matches_headings(self, document_xml):
        """Number of _toc_* bookmarks should equal number of TOC entries."""
        expected = _pre_scan_headings(SAMPLE_BODY, title=SAMPLE_TITLE)

        tree = ET.fromstring(document_xml)
        bookmarks = tree.findall(".//w:bookmarkStart", NS)
        toc_bookmarks = [
            bm for bm in bookmarks
            if (bm.get(f"{{{NS['w']}}}name") or "").startswith("_toc_")
        ]
        assert len(toc_bookmarks) == len(expected), (
            f"Expected {len(expected)} bookmarks, got {len(toc_bookmarks)}"
        )


# ---------------------------------------------------------------------------
# 3. PAGEREF fields in TOC page
# ---------------------------------------------------------------------------

class TestPagerefFields:
    """PAGEREF _toc_N \\h fields must exist in the document."""

    def test_pageref_present(self, document_xml):
        matches = re.findall(r"PAGEREF\s+_toc_\d+", document_xml)
        assert len(matches) > 0, "No PAGEREF _toc_* fields found"

    def test_pageref_count_matches_entries(self, document_xml):
        expected = _pre_scan_headings(SAMPLE_BODY, title=SAMPLE_TITLE)
        matches = re.findall(r"PAGEREF\s+_toc_\d+", document_xml)
        assert len(matches) == len(expected), (
            f"Expected {len(expected)} PAGEREF fields, got {len(matches)}"
        )


# ---------------------------------------------------------------------------
# 4. TOC entry count matches body heading count
# ---------------------------------------------------------------------------

class TestTocEntryCount:
    """The visible TOC should have exactly as many entries as body headings."""

    def test_entry_count(self, document_xml):
        expected = _pre_scan_headings(SAMPLE_BODY, title=SAMPLE_TITLE)
        # Each TOC entry has a tab character followed by PAGEREF
        # Count PAGEREF occurrences as proxy for visible entries
        matches = re.findall(r"PAGEREF\s+_toc_\d+", document_xml)
        assert len(matches) == len(expected)


# ---------------------------------------------------------------------------
# 5. Non-body heading blacklist
# ---------------------------------------------------------------------------

class TestBlacklist:
    """_pre_scan_headings must filter out non-body headings."""

    @pytest.mark.parametrize("heading", [
        "摘要", "摘 要", "中文摘要",
        "Abstract", "abstract", "ABSTRACT",
        "致谢", "致 谢",
        "参考文献",
    ])
    def test_blacklisted_headings_excluded(self, heading):
        body = f"# {heading}\n正文内容\n# 第一章 绪论\n正文\n"
        entries = _pre_scan_headings(body, title="某论文题目", include_back_matter=False)
        texts = [e["text"] for e in entries]
        assert heading not in texts, f"'{heading}' should be filtered out"

    def test_title_excluded(self):
        body = "# 我的毕业论文\n# 第一章 绪论\n正文\n"
        entries = _pre_scan_headings(body, title="我的毕业论文")
        texts = [e["text"] for e in entries]
        assert "我的毕业论文" not in texts

    def test_normal_headings_kept(self):
        body = "# 1 绪论\n## 1.1 研究背景\n正文\n"
        entries = _pre_scan_headings(body, title="某论文")
        assert len(entries) == 4
        assert entries[0]["text"] == "1 绪论"
        assert entries[1]["text"] == "1.1 研究背景"
        assert entries[-2]["text"] == "参考文献"
        assert entries[-1]["text"] == "致谢"
