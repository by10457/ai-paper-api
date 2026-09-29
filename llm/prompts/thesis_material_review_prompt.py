"""文献综述概述与主题比较模板。"""

from langchain_core.prompts import ChatPromptTemplate

from llm.prompts.thesis_material_common import CITATION_RULES, MATERIAL_RULES

# 摘要、引言和国内外研究现状。
REVIEW_OVERVIEW_PROMPT = ChatPromptTemplate.from_messages(
    [
        ("system", MATERIAL_RULES + CITATION_RULES + "你是学术文献综述作者。严格输出JSON对象，不要Markdown。"),
        (
            "human",
            "课题：{title}\n补充信息：{context}\n真实文献：\n{references}\n"
            "生成文本字段{constraints}、keywords(3-6个字符串)。依据资料中可核验的研究地域组织国内外研究现状；地域无法确认时明确资料不足，不编造归属。"
            "domestic_research表示国内研究现状，foreign_research表示国外研究现状。"
            "当前综述结构为引言、国内研究现状、国外研究现状、主题分类、研究方法比较、研究不足、发展趋势、结论。"
            "摘要和引言不得声称本文按源论文的绪论、系统设计等章节组织。英文文献不等于国外研究，不能仅凭语言推断研究地区。",
        ),
    ]
)
# 主题数量和字数预算由服务计算，不在模板写死。
REVIEW_ANALYSIS_PROMPT = ChatPromptTemplate.from_messages(
    [
        ("system", MATERIAL_RULES + CITATION_RULES + "你是学术综述评审专家。严格输出JSON对象，不要Markdown。"),
        (
            "human",
            "课题：{title}\n补充信息：{context}\n真实文献：\n{references}\n"
            "生成themes数组{theme_count}项，每项含title和content，content为{minimum}-{maximum}字，"
            "比较题名明确涉及的研究主题，未提供摘要或全文时，不得断言作者的方法、优缺点、成果或遗漏。"
            "可围绕本课题提出待验证的比较维度、研究问题和可执行的核查步骤，明确是本综述的分析框架而非文献结论。"
            "发展趋势必须具体说明拟探索的方向及原因，不得只列题名后写‘这些趋势’；另生成文本字段：{constraints}。",
        ),
    ]
)
