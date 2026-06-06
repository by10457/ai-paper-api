from llm.prompts.thesis_reference_prompt import (
    REFERENCE_FILTER_PROMPT,
    REFERENCE_SCHOLAR_KEYWORD_PROMPT,
    REFERENCE_WFDATA_KEYWORD_PROMPT,
)


def test_reference_keyword_prompts_escape_json_examples() -> None:
    """参考文献提示词中的 JSON 示例不能被 LangChain 识别为模板变量。"""

    REFERENCE_WFDATA_KEYWORD_PROMPT.format_messages(title="论文题目", outline="论文大纲")
    REFERENCE_SCHOLAR_KEYWORD_PROMPT.format_messages(title="论文题目", outline="论文大纲")
    REFERENCE_FILTER_PROMPT.format_messages(title="论文题目", results_json="[]", keep_count=3)
