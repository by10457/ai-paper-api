"""管理端用户服务测试。"""

import asyncio
from datetime import datetime
from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi import HTTPException

from models.user import User
from schemas.admin import AdminUserCreateRequest
from services.admin import users as admin_users
from services.admin.users import AUTO_EMAIL_DOMAIN, AdminUserService


class _FakeQuery:
    def __init__(self, exists: bool) -> None:
        self._exists = exists

    async def exists(self) -> bool:
        return self._exists


class _FakeUserModel:
    created_kwargs: dict[str, Any] = {}

    @staticmethod
    def filter(**_kwargs: object) -> _FakeQuery:
        return _FakeQuery(False)

    @staticmethod
    async def create(**kwargs: Any) -> SimpleNamespace:
        _FakeUserModel.created_kwargs = kwargs
        return SimpleNamespace(
            id=1,
            username=kwargs["username"],
            avatar=kwargs.get("avatar"),
            nickname=kwargs.get("nickname"),
            email=kwargs["email"],
            points=kwargs["points"],
            role=kwargs["role"],
            is_disabled=False,
            created_at=datetime.now(),
            updated_at=datetime.now(),
            api_token=kwargs["api_token"],
            api_token_created_at=kwargs["api_token_created_at"],
            api_token_last_used_at=None,
            api_token_call_count=kwargs["api_token_call_count"],
        )


def test_resolve_create_email_generates_internal_email(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, object]] = []

    def fake_filter(**kwargs: object) -> _FakeQuery:
        calls.append(kwargs)
        return _FakeQuery(False)

    monkeypatch.setattr(admin_users.User, "filter", fake_filter)
    data = AdminUserCreateRequest(username="Demo User", password="demo123456", nickname=None, avatar=None)

    email = asyncio.run(AdminUserService._resolve_create_email(data))

    assert email.startswith("demo-user.")
    assert email.endswith(f"@{AUTO_EMAIL_DOMAIN}")
    assert calls == [{"email": email}]


def test_resolve_create_email_rejects_duplicate_explicit_email(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_filter(**kwargs: object) -> _FakeQuery:
        assert kwargs == {"email": "demo@example.com"}
        return _FakeQuery(True)

    monkeypatch.setattr(admin_users.User, "filter", fake_filter)
    data = AdminUserCreateRequest(
        username="demo",
        password="demo123456",
        email="demo@example.com",
        nickname=None,
        avatar=None,
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(AdminUserService._resolve_create_email(data))

    assert exc_info.value.status_code == 409


def test_create_user_initializes_api_token(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_write_audit_log(**_kwargs: object) -> None:
        return None

    monkeypatch.setattr(admin_users, "User", _FakeUserModel)
    monkeypatch.setattr(admin_users, "write_audit_log", fake_write_audit_log)
    monkeypatch.setattr(admin_users.PointLedger, "create", lambda **_kwargs: None)
    monkeypatch.setattr(admin_users.secrets, "token_urlsafe", lambda _length: "generated-token")
    data = AdminUserCreateRequest(username="demo", password="demo123456", nickname=None, avatar=None)

    asyncio.run(AdminUserService.create_user(data, cast(User, SimpleNamespace(id=99))))

    assert _FakeUserModel.created_kwargs["api_token"] == "generated-token"
    assert _FakeUserModel.created_kwargs["api_token_call_count"] == 0
    assert _FakeUserModel.created_kwargs["api_token_created_at"] is not None
