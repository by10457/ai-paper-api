"""文献综述概述与主题比较模板。"""

from langchain_core.prompts import ChatPromptTemplate

from llm.prompts.thesis_material_common import CITATION_RULES, MATERIAL_RULES

# 摘要、引言和国内外研究现状。
REVIEW_OVERVIEW_PROMPT = ChatPromptTemplate.from_messages([
    ("system", MATERIAL_RULES + CITATION_RULES + "你是学术文献综述作者。严格输出JSON对象，不要Markdown。"),
    ("human", "课题：{title}\n补充信息：{context}\n真实文献：\n{references}\n"
     "生成文本字段{constraints}、keywords(3-6个字符串)。国内外研究必须综合比较给定资料。"),
])
# 主题数量和字数预算由服务计算，不在模板写死。
REVIEW_ANALYSIS_PROMPT = ChatPromptTemplate.from_messages([
    ("system", MATERIAL_RULES + CITATION_RULES + "你是学术综述评审专家。严格输出JSON对象，不要Markdown。"),
    ("human", "课题：{title}\n补充信息：{context}\n真实文献：\n{references}\n"
     "生成themes数组{theme_count}项，每项含title和content，content为{minimum}-{maximum}字，"
     "比较多篇文献并包含已有做法、不同观点、优缺点和小结；另生成文本字段：{constraints}。"),
])
