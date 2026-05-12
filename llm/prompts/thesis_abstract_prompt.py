from langchain_core.prompts import ChatPromptTemplate

ABSTRACT_COMBINED_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            (
                "你是一位专业的学术论文助手。根据提供的论文内容片段，同时撰写中文摘要和对应的英文摘要。\n\n"
                "要求：\n"
                "1. 先写中文摘要（300-500 字），涵盖：研究背景、研究目的、研究方法、主要结论\n"
                "2. 再写英文摘要（200-300 words），必须是中文摘要的忠实翻译，不可重新解读原文\n"
                "3. 使用第三人称，不出现「本人」「我」\n"
                "4. 不加「摘要」「Abstract」等标题\n\n"
                "输出格式（严格遵守，不可省略分隔符）：\n"
                "===中文摘要===\n"
                "（中文摘要正文）\n"
                "【关键词】词1；词2；词3；词4；词5\n\n"
                "===英文摘要===\n"
                "（英文摘要正文，为上方中文摘要的忠实翻译）\n"
                "【KEY WORDS】word1; word2; word3; word4; word5"
            ),
        ),
        ("human", "{text_sample}"),
    ]
)

ACKNOWLEDGMENT_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            (
                "你是一位即将毕业的大学生，正在撰写本科毕业论文的致谢部分。\n\n"
                "要求：\n"
                "1. 字数 200-350 字\n"
                "2. 感谢对象包括：指导教师、同学、家人\n"
                "3. 语言真诚自然，不过度煽情，不使用模板套话\n"
                "4. 只输出致谢正文，不加「致谢」标题"
            ),
        ),
        ("human", "论文标题：{title}\n指导教师：{advisor}"),
    ]
)
