"""完整论文个人信息缺失识别与显式占位规则。"""

from __future__ import annotations

_PROFILE_LABELS = {
    "author": "作者姓名",
    "advisor": "指导教师",
    "major": "专业名称",
    "school": "学院（系）",
    "year_month": "年月",
    "student_id": "学号",
    "student_class": "班级",
}
_LEGACY_PLACEHOLDERS = {
    "author": {"", "作者姓名", "某某某"},
    "advisor": {"", "指导教师", "指导教师（姓名、职称、单位）"},
    "major": {"", "专业名称"},
    "school": {"", "XX大学XX学院", "某某大学", "某某学院"},
    "year_month": {""},
    "student_id": {"", "20XXXXXXXXXX"},
    "student_class": {""},
}


# 把旧占位值转换为醒目提示，并返回缺失字段
def normalize_thesis_profile(profile: dict[str, str]) -> tuple[dict[str, str], list[str]]:
    """规范完整论文封面及声明页个人信息。

    Args:
        profile: 论文生成参数中的个人信息字段。

    Returns:
        可直接用于 DOCX 的显式占位数据和缺失字段列表。
    """

    normalized: dict[str, str] = {}
    missing_fields: list[str] = []
    for field, label in _PROFILE_LABELS.items():
        value = str(profile.get(field) or "").strip()
        if value in _LEGACY_PLACEHOLDERS[field]:
            missing_fields.append(field)
            normalized[field] = f"【待补充：{label}】"
        else:
            normalized[field] = value
    return normalized, missing_fields


def mark_acknowledgment_as_draft(acknowledgment: str, *, missing_profile_fields: list[str]) -> str:
    """个人信息缺失时，把模型致谢显式标为待用户按真实经历修改的草稿。"""

    if not missing_profile_fields:
        return acknowledgment
    notice = "【待补充：以下致谢为通用草稿，请结合本人真实经历、指导教师及协助人员信息修改。】"
    return f"{notice}\n\n{acknowledgment}" if acknowledgment else notice


__all__ = ["mark_acknowledgment_as_draft", "normalize_thesis_profile"]
