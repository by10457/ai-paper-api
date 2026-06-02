from docx.document import Document as DocxDocument
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

from services.thesis.document.formatting import _apply_fixed_line_spacing
from services.thesis.document.sections import _clear_header_footer


def _init_styles(document: DocxDocument) -> None:
    """设置文档默认样式和标题样式。"""
    normal_style = document.styles["Normal"]
    normal_style.font.name = "宋体"
    normal_style.font.size = Pt(12)
    normal_style.paragraph_format.first_line_indent = Cm(0.74)
    normal_style.paragraph_format.space_before = Pt(0)
    normal_style.paragraph_format.space_after = Pt(0)
    _apply_fixed_line_spacing(normal_style.paragraph_format, pt=22)

    normal_r_pr = normal_style.element.get_or_add_rPr()
    normal_r_fonts = normal_r_pr.get_or_add_rFonts()
    normal_r_fonts.set(qn("w:eastAsia"), "宋体")
    normal_r_fonts.set(qn("w:ascii"), "Times New Roman")
    normal_r_fonts.set(qn("w:hAnsi"), "Times New Roman")

    heading_config = [
        (1, 16, True),
        (2, 14, True),
        (3, 12, True),
    ]
    for level, size, bold in heading_config:
        style = document.styles[f"Heading {level}"]
        style.font.name = "宋体"
        style.font.size = Pt(size)
        style.font.bold = bold
        style.font.color.rgb = RGBColor(0, 0, 0)
        r_fonts = style.element.get_or_add_rPr().get_or_add_rFonts()
        r_fonts.set(qn("w:eastAsia"), "宋体")
        r_fonts.set(qn("w:ascii"), "Times New Roman")
        r_fonts.set(qn("w:hAnsi"), "Times New Roman")
        style.paragraph_format.space_before = Pt(6)
        style.paragraph_format.space_after = Pt(6)
        _apply_fixed_line_spacing(style.paragraph_format, pt=22)
        if level == 1:
            style.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.CENTER

def _setup_page(document: DocxDocument) -> None:
    """设置首页 section 的页面尺寸和页边距。"""
    section = document.sections[0]
    section.page_width = Cm(21)
    section.page_height = Cm(29.7)
    section.top_margin = Cm(3)
    section.bottom_margin = Cm(2.7)
    section.left_margin = Cm(3)
    section.right_margin = Cm(3)
    section.header_distance = Cm(2)
    section.footer_distance = Cm(2)
    _clear_header_footer(section)
