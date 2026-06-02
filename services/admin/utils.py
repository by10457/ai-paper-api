"""管理端展示相关的轻量工具函数。"""


def mask_secret(value: str | None) -> str:
    """脱敏展示密钥或调用 token。"""

    if not value:
        return ""
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}****{value[-4:]}"
