from llm.prompts.thesis_fulltext_prompt import THESIS_FULLTEXT_PROMPT


def test_fulltext_prompt_escapes_mermaid_example_braces() -> None:
    messages = THESIS_FULLTEXT_PROMPT.format_messages(
        outline="# 1 绪论",
        target_word_count=8000,
        target_word_count_max=9600,
        references="[1]张三.测试文献[J].测试期刊,2026.",
        codetype_instruction="",
        writing_requirements="避免编造真实运营数据。",
        confirmed_technologies="Spring Boot、Vue",
        evidence_instruction="未提供真实测试数据，禁止输出实测结论或数据图。",
    )

    assert any('B{"是否通过校验"}' in message.content for message in messages)
    assert any("避免编造真实运营数据" in message.content for message in messages)
    assert any("禁止输出实测结论" in message.content for message in messages)
