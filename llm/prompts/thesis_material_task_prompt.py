"""任务书结构与验收指标模板。"""

from langchain_core.prompts import ChatPromptTemplate

from llm.prompts.thesis_material_common import MATERIAL_RULES

# 数值要求只接受用户已确认的输入，不能由模型补造。
CONFIRMED_METRIC_RULE = "用户已明确提供数值要求，只能复述这些数值，不得自行增加阈值。"
SUGGESTED_METRIC_RULE = (
    "用户未提供数值要求，禁止编造响应时间、并发量、覆盖率、准确率、占比或运行天数等确定性阈值；"
    "应写可核验的质量要求；确需举例的数值必须标注‘建议值，待导师确认’。"
)
# 任务书各字段与服务端结构校验一一对应。
TASK_BOOK_PROMPT = ChatPromptTemplate.from_messages([
    ("system", MATERIAL_RULES + "你是高职和本科毕业设计任务书编制专家。严格输出JSON对象，不要填写日期。"),
    ("human", "课题：{title}\n补充信息：{context}\n选题类型：{topic_type}\n"
     "生成design_background(100-200字)、technology_stack(字符串数组；不适用时为空)、"
     "design_goals(5-10个可验收目标)、main_indicators(4-8个可测量或可核验指标)、"
     "module_tasks(4-8项，每项含name、role、responsibilities、boundary；非技术课题按研究任务组织)、"
     "deliverable_forms(2-5项)、deliverable_requirements(2-5项)。目标、指标与任务不得重复。{metric_instruction}"),
])
