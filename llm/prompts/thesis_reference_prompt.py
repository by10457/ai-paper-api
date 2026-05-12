from langchain_core.prompts import ChatPromptTemplate

REFERENCE_KEYWORD_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            (
                "你是学术搜索助手。根据论文标题和大纲，提取最适合在 Google Scholar 搜索的关键词。\n\n"
                "输出格式（严格 JSON，不要加 ```）：\n"
                '{{"zh": "中文关键词组合", "en": ["英文关键词组合1", "英文关键词组合2"]}}\n\n'
                "要求：\n"
                "- zh：1 个中文搜索串，用于搜索中文文献\n"
                "- en：1 个英文搜索串，用于搜索英文文献\n"
                "- 每个搜索串 2-4 个词，不要加引号"
            ),
        ),
        ("human", "标题：{title}\n\n大纲：{outline}"),
    ]
)

REFERENCE_FILTER_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            (
                "你是学术文献筛选助手。从搜索结果中筛选与论文最相关的文献。\n\n"
                "输出格式（严格 JSON，不要加 ```）：\n"
                '{{"keep": [0, 1, 3, ...]}}\n\n'
                "要求：\n"
                "- 保留约 {keep_count} 篇最相关的文献\n"
                "- 优先保留：与论文核心主题直接相关、有明确期刊/会议来源和发表年份的文献\n"
                "- 排除：无法确认来源的、标题明显不相关的、没有年份信息的"
            ),
        ),
        ("human", "论文标题：{title}\n\n搜索结果（JSON）：{results_json}"),
    ]
)
