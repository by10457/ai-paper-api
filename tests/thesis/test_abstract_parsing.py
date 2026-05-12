from services.thesis.abstract_service import _parse_combined_abstract


def test_parse_combined_abstract_accepts_bracket_keywords() -> None:
    raw = """===中文摘要===
中文摘要正文。
【关键词】校途；论文；系统

===英文摘要===
English abstract body.
【KEY WORDS】school route; thesis; system"""

    result = _parse_combined_abstract(raw)

    assert result["abstract_zh"] == "中文摘要正文。"
    assert result["keywords_zh"] == "校途；论文；系统"
    assert result["abstract_en"] == "English abstract body."
    assert result["keywords_en"] == "school route; thesis; system"


def test_parse_combined_abstract_keeps_legacy_keyword_formats() -> None:
    raw = """===中文摘要===
中文摘要正文。
关键词：校途；论文

===英文摘要===
English abstract body.
Keywords: school route; thesis"""

    result = _parse_combined_abstract(raw)

    assert result["keywords_zh"] == "校途；论文"
    assert result["keywords_en"] == "school route; thesis"
