from typing import Any, cast

from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor


def _toc_int(value: object) -> int:
    return int(cast(int | str, value))


def _set_run_font(
    run: Any,
    zh_font: str = "宋体",
    en_font: str = "Times New Roman",
    size_pt: float | None = None,
    bold: bool | None = None,
    underline: bool | None = None,
    color_rgb: RGBColor | None = None,
) -> None:
    """统一设置 run 的中英文字体、字号和样式。"""
    r_pr = run._element.get_or_add_rPr()
    r_fonts = r_pr.get_or_add_rFonts()
    r_fonts.set(qn("w:eastAsia"), zh_font)
    r_fonts.set(qn("w:ascii"), en_font)
    r_fonts.set(qn("w:hAnsi"), en_font)
    run.font.name = en_font
    if size_pt is not None:
        run.font.size = Pt(size_pt)
    if bold is not None:
        run.bold = bold
    if underline is not None:
        run.underline = underline
    if color_rgb is not None:
        run.font.color.rgb = color_rgb


def _apply_fixed_line_spacing(paragraph_format: Any, pt: float = 22) -> None:
    """应用固定值行距。"""
    p_pr = paragraph_format._element.get_or_add_pPr()
    for old in p_pr.findall(qn("w:spacing")):
        p_pr.remove(old)
    spacing = OxmlElement("w:spacing")
    spacing.set(qn("w:line"), str(int(pt * 20)))
    spacing.set(qn("w:lineRule"), "exact")
    p_pr.append(spacing)


def _set_page_numbering(section: Any, start: int | None = None, number_format: str | None = None) -> None:
    """设置当前 section 页码格式；start 为 None 时自然延续。"""
    sect_pr = section._sectPr
    for old in sect_pr.findall(qn("w:pgNumType")):
        sect_pr.remove(old)
    pg_num = OxmlElement("w:pgNumType")
    if number_format:
        pg_num.set(qn("w:fmt"), number_format)
    if start is not None:
        pg_num.set(qn("w:start"), str(start))
    sect_pr.append(pg_num)
