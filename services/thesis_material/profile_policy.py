"""论文材料个人信息缺失规则。"""

from __future__ import annotations

from typing import Any

_PROFILE_LABELS = {
    "school": "学校",
    "college": "学院",
    "name": "学生姓名",
    "student_no": "学号",
    "class_name": "班级",
    "major": "专业",
    "internal_advisor": "校内指导教师",
    "enterprise_advisor": "企业指导教师",
    "year_month": "年月",
}

_REQUIRED_PROFILE_FIELDS = {
    "proposal_report": (
        "school",
        "name",
        "student_no",
        "class_name",
        "major",
        "internal_advisor",
        "year_month",
    ),
    "task_book": (
        "school",
        "college",
        "name",
        "student_no",
        "class_name",
        "internal_advisor",
        "enterprise_advisor",
    ),
}


def missing_profile_fields(document_type: str, request: dict[str, Any]) -> list[str]:
    """返回当前材料会显示占位提示的个人信息字段。"""

    raw_profile = request.get("student_profile")
    profile = raw_profile if isinstance(raw_profile, dict) else {}
    return [
        field for field in _REQUIRED_PROFILE_FIELDS.get(document_type, ()) if not str(profile.get(field) or "").strip()
    ]


def profile_with_placeholders(request: dict[str, Any]) -> dict[str, str]:
    """生成明确可识别的待补充值，避免伪装成已填写的个人信息。"""

    raw_profile = request.get("student_profile")
    profile = raw_profile if isinstance(raw_profile, dict) else {}
    return {field: str(profile.get(field) or f"【待补充：{label}】") for field, label in _PROFILE_LABELS.items()}


__all__ = ["missing_profile_fields", "profile_with_placeholders"]
