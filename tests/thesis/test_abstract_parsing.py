from services.thesis.content.abstract_service import _limit_abstract_lengths, _parse_combined_abstract


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


def test_limit_abstract_lengths_keeps_english_abstract_on_one_page() -> None:
    """英文摘要应限制在单页友好的长度范围。"""

    result = _limit_abstract_lengths(
        {
            "abstract_zh": "中文摘要。",
            "abstract_en": " ".join(["word"] * 210 + ["final."] + ["overflow"] * 80),
            "keywords_zh": "关键词",
            "keywords_en": "keyword",
        }
    )

    assert len(result["abstract_en"].split()) <= 220
    assert result["abstract_en"].endswith(".")
