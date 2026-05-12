from services.thesis import reference_service


def test_chinese_authors_use_half_width_commas() -> None:
    line = reference_service._format_one_reference(
        {
            "title": "智能管理系统研究",
            "publication_info": {
                "authors": [
                    {"name": "张三"},
                    {"name": "李四"},
                    {"name": "王五"},
                ],
                "summary": "张三 - 软件学报, 2024, 10(2), 11-18 - example.com",
            },
        },
        1,
        is_zh=True,
    )

    assert line.startswith("[1]张三,李四,王五.")
    assert "，" not in line


def test_journal_source_is_not_misclassified_as_dissertation() -> None:
    line = reference_service._format_one_reference(
        {
            "title": "财政信息系统研究",
            "publication_info": {
                "summary": "作者 - 湖南财政经济学院学报, 2024, 5(2), 31-36 - example.com",
            },
        },
        1,
        is_zh=True,
    )

    assert "[J]" in line
    assert "[D]" not in line


def test_crossref_journal_prevents_dissertation_marker() -> None:
    line = reference_service._format_one_reference(
        {
            "title": "系统设计研究",
            "publication_info": {"summary": "作者 - 某大学, 2024 - example.com"},
            "crossref_journal": "Journal of Systems",
            "crossref_year": "2024",
            "crossref_volume": "7",
            "crossref_issue": "2",
            "crossref_page": "10-18",
        },
        1,
        is_zh=False,
    )

    assert "[J]" in line
    assert "[D]" not in line


def test_incomplete_journal_reference_is_skipped_before_return() -> None:
    line = reference_service._format_one_reference(
        {
            "title": "缺页码期刊研究",
            "publication_info": {"summary": "作者 - 某期刊, 2024 - example.com"},
        },
        1,
        is_zh=True,
    )

    assert line == ""
