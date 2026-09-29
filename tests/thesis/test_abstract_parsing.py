from services.thesis.content.abstract_service import _parse_combined_abstract


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


# 版式不得通过截断译文来适配单页。
def test_english_abstract_keeps_conclusion_after_220_words() -> None:
    """超过旧版截断位置的结论仍应保留。"""
    english = " ".join(["word"] * 230) + " No empirical validation has been performed."
    result = _parse_combined_abstract("===中文摘要===\n尚未实测。\n===英文摘要===\n" + english)
    assert result["abstract_en"] == english
