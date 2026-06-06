from langchain_core.prompts import ChatPromptTemplate

REFERENCE_WFDATA_KEYWORD_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            (
                "你是参考文献检索关键词规划助手。根据论文标题和大纲，为万方文献检索和英文文献检索生成多批查询词。\n\n"
                "输出格式（严格 JSON，不要加 ```）：\n"
                "{{\n"
                '  "zh": "最直接的中文主查询",\n'
                '  "zh_related": ["中文关联查询1", "中文关联查询2", "..."],\n'
                '  "zh_extended": ["中文延伸查询1", "中文延伸查询2", "..."],\n'
                '  "en": ["英文主查询1", "英文主查询2"],\n'
                '  "en_related": ["英文关联查询1", "英文关联查询2"],\n'
                '  "en_extended": ["英文延伸查询1", "英文延伸查询2"]\n'
                "}}\n\n"
                "要求：\n"
                "- 关键词要覆盖：论文核心对象、应用场景、技术路线、上位概念、相邻研究方向。\n"
                "- 中文检索主要用于万方文献检索，要优先使用中文学术表达，不要只堆砌英文技术词。\n"
                "- zh 是最直接的中文查询；zh_related 给 3-5 个强相关查询；zh_extended 给 3-5 个更宽泛但仍相关的查询。\n"
                "- en 给 2-3 个英文主查询；en_related/en_extended 各给 1-3 个英文查询。\n"
                "- 每个查询 2-6 个词，不要加引号，不要写 AND/OR/NOT，不要包含“论文”“参考文献”等无效词。\n"
                "- 查询词可以适当放宽，目标是尽量检索到足够多且相关的参考文献。"
            ),
        ),
        ("human", "标题：{title}\n\n大纲：{outline}"),
    ]
)

REFERENCE_SCHOLAR_KEYWORD_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            (
                "你是 Google Scholar 学术搜索关键词助手。根据论文标题和大纲，生成适合 SerpAPI Google Scholar 检索的查询词。\n\n"
                "输出格式（严格 JSON，不要加 ```）：\n"
                '{{"zh": "中文学术查询", "en": ["英文查询1", "英文查询2", "英文查询3"]}}\n\n'
                "要求：\n"
                "- zh：1 个中文学术查询，用于补充检索中文相关文献。\n"
                "- en：2-3 个英文查询，用于检索英文论文，优先使用国际通用学术表达。\n"
                "- 每个查询 2-6 个词，不要加引号，不要写 AND/OR/NOT。\n"
                "- 英文查询要覆盖核心技术、应用场景和上位研究方向，不要只翻译论文标题。\n"
                "- 避免过宽的泛词，例如 research、paper、system、method 单独出现。"
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
