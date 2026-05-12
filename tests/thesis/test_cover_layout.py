import tempfile
import zipfile
from pathlib import Path

from services.thesis.docx_builder import build_word_document


def test_cover_main_title_does_not_use_body_exact_line_spacing() -> None:
    out = Path(tempfile.mktemp(suffix=".docx"))
    try:
        build_word_document(
            title="新媒体语境下非物质文化遗产短视频传播策略研究",
            full_text="# 第一章 绪论\n正文。\n",
            output_path=str(out),
            author="测试用户",
            advisor="指导教师",
            degree_type="学士",
            major="新闻传播学",
            school="人文与传播学院",
            year_month="2026年4月",
            abstract_zh="中文摘要",
            keywords_zh="关键词",
            abstract_en="English abstract",
            keywords_en="keywords",
            acknowledgment="感谢。",
            references="[1] 文献。",
            placeholders=[],
            image_paths={},
        )

        with zipfile.ZipFile(out) as zf:
            xml = zf.read("word/document.xml").decode("utf-8", errors="ignore")

        idx = xml.find("学士学位论文")
        assert idx != -1
        window = xml[max(0, idx - 500): idx + 200]
        assert 'w:lineRule="exact"' not in window
    finally:
        out.unlink(missing_ok=True)
