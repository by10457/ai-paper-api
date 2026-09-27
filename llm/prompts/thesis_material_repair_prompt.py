"""材料篇幅、缺失字段与文献引用修订模板。"""

from langchain_core.prompts import ChatPromptTemplate

from llm.prompts.thesis_material_common import CITATION_RULES, MATERIAL_RULES

# 保留引用闭环，超长改写与不足扩写使用同一长度口径。
LENGTH_REPAIR_PROMPT = ChatPromptTemplate.from_messages([
    ("system", MATERIAL_RULES + CITATION_RULES + "你是严格执行篇幅要求的学术编辑。只输出修订后的连续正文，不要标题、说明或字数统计。"),
    ("human", "课题：{title}\n字段：{field}\n当前字符数：{length}\n统一规划：{context}\n"
     "原文（超长时可能省略）：\n{original}\n可用参考文献：\n{references}\n内容要求：{requirements}\n"
     "请修订到约{target}字，硬性范围为{minimum}-{maximum}字。写成{paragraph_count}个自然段，"
     "每段约{paragraph_length}字。按非空白字符统计，汉字、标点、英文字母和数字逐字符计数；"
     "超长时必须重新组织语言，不得照抄。必须保留这些引用编号：{citations}；列表为空时不得增加编号。"),
])
# 补全缺失字段而不重写已有合格正文。
MISSING_FIELDS_PROMPT = ChatPromptTemplate.from_messages([
    ("system", MATERIAL_RULES + CITATION_RULES + "你是学术综述评审专家。只补全指定JSON文本字段，不要输出其他字段或Markdown。"),
    ("human", "课题：{title}\n统一规划：{context}\n真实文献：\n{references}\n"
     "上一轮缺少字段：{missing_fields}。请严格输出这些字段，其中{constraints}。"),
])
# 开题报告现状区块补齐引用。
PROPOSAL_COVERAGE_PROMPT = ChatPromptTemplate.from_messages([
    ("system", MATERIAL_RULES + CITATION_RULES + "你是开题报告文献综述作者。只输出修订后的连续正文，不要标题。"),
    ("human", "课题：{title}\n统一规划：{context}\n原文：\n{original}\n"
     "下列真实文献尚未在正文引用：\n{references}\n保留主要论证和已有引用，逐篇说明题名与课题的关系，"
     "准确使用每个给定编号，不得新增文献。全文保持在{minimum}-{maximum}字。"),
])
# 综述主题区块补齐引用。
REVIEW_COVERAGE_PROMPT = ChatPromptTemplate.from_messages([
    ("system", MATERIAL_RULES + CITATION_RULES + "你是学术综述评审专家。只输出一个主题的连续正文，不要标题。"),
    ("human", "课题：{title}\n统一规划：{context}\n尚未引用的真实文献：\n{references}\n"
     "写一个综合比较主题，逐篇使用给定编号，说明已有做法、不同观点、优缺点和小结。"
     "编号必须原样独立出现，例如[1]和[2]，禁止合并写成[1-2]、[1,2]。"),
])
