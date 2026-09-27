"""开题报告分阶段生成模板。"""

from langchain_core.prompts import ChatPromptTemplate

from llm.prompts.thesis_material_common import CITATION_RULES, MATERIAL_RULES

# 用户已确认提纲时直接复用，缺失时按课题自主判断层级。
CONFIRMED_OUTLINE_RULE = "已有用户确认的论文大纲，无需生成writing_outline；研究内容与方法应围绕该大纲展开。"
GENERATED_OUTLINE_RULE = (
    "生成writing_outline数组，包含1-20个一级章节，每项为{title,sections}，"
    "sections为2-5项数组，每项为{title,subsections}，subsections为0-4个三级标题字符串。"
    "默认两级，按篇幅和内容需要局部细化到三级，不强制三级。标题禁止自带章节编号。"
)

# 开题报告研究目的与意义。
PROPOSAL_PURPOSE_PROMPT = ChatPromptTemplate.from_messages([
    ("system", MATERIAL_RULES + CITATION_RULES + "你是毕业论文开题报告写作专家。只输出连续正文，不要标题。"),
    ("human", "课题：{title}\n补充信息：{context}\n写{minimum}-{maximum}字研究目的，"
     "涵盖背景、现实问题、必要性、应用价值和研究目标。\n真实文献：\n{references}"),
])
# 国内外现状与趋势，保持可核验来源边界。
PROPOSAL_STATUS_PROMPT = ChatPromptTemplate.from_messages([
    ("system", MATERIAL_RULES + CITATION_RULES + "你是严谨的学术文献综述作者。只输出连续正文。"),
    ("human", "课题：{title}\n补充信息：{context}\n围绕传统方案、国内外研究、主流方法、应用场景、"
     "现有不足和趋势写{minimum}-{maximum}字。引用至少{citation_count}篇给定文献。\n真实文献：\n{references}"),
])
# 研究内容、方法、难点与可行性等结构化区块。
PROPOSAL_ANALYSIS_PROMPT = ChatPromptTemplate.from_messages([
    ("system", MATERIAL_RULES + CITATION_RULES + "你是毕业论文研究方案专家。严格输出JSON对象，不要Markdown。"),
    ("human", "课题：{title}\n补充信息：{context}\n生成以下文本字段：{constraints}；"
     "{outline_requirement}内容必须具体且互不重复。\n真实文献：\n{references}"),
])
