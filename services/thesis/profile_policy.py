"""完整论文使用固定占位，不接收或推断个人信息。"""

from __future__ import annotations

# 文档离线填写项，不是接口输入字段。
_PROFILE_LABELS = {
    "author": "作者姓名",
    "advisor": "指导教师",
    "major": "专业名称",
    "school": "学院（系）",
    "year_month": "年月",
    "student_id": "学号",
    "student_class": "班级",
    "degree_type": "学位类别",
}


# 生成固定占位及离线待填写字段清单
def thesis_profile_placeholders() -> tuple[dict[str, str], list[str]]:
    """生成完整论文封面及声明页的固定占位。

    Returns:
        可直接用于 DOCX 的显式占位数据和缺失字段列表。
    """

    return {field: f"【待补充：{label}】" for field, label in _PROFILE_LABELS.items()}, list(_PROFILE_LABELS)


# 致谢由用户下载后填写，不调用模型虚构个人经历
def acknowledgment_placeholder() -> str:
    """返回明确要求离线填写的致谢占位文本。"""
    return (
        "【待补充：致谢内容需依据本人真实经历填写。请补充指导教师、协助人员及需致谢事项后，"
        "下载后在文档中修改本页，无需通过接口提交个人信息。】"
    )


__all__ = ["acknowledgment_placeholder", "thesis_profile_placeholders"]
