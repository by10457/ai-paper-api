"""安全工具测试。"""

import pytest

from core.security import hash_password, verify_password


def test_hash_password_and_verify_password() -> None:
    password = "demo123456"

    hashed = hash_password(password)

    assert hashed.startswith("$2")
    assert verify_password(password, hashed)
    assert not verify_password("wrong-password", hashed)


def test_hash_password_rejects_too_long_password() -> None:
    with pytest.raises(ValueError, match="72 字节"):
        hash_password("a" * 73)


def test_verify_password_returns_false_for_too_long_password() -> None:
    hashed = hash_password("demo123456")

    assert not verify_password("a" * 73, hashed)
