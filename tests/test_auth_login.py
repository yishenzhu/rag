"""Password hashing and JWT login tests."""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from rag.app.auth_routes import authenticate_user
from rag.security.auth import (
    TokenError,
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)

SECRET = "0123456789abcdef0123456789abcdef"


def test_password_hash_and_verify():
    hashed = hash_password("secret123")
    assert hashed != "secret123"
    assert verify_password("secret123", hashed)
    assert not verify_password("wrong", hashed)


def test_token_roundtrip_and_validation():
    user_id = uuid4()
    token = create_access_token(user_id, "a@b.com", SECRET, 60)
    payload = decode_access_token(token, SECRET)
    assert payload.user_id == user_id
    assert payload.email == "a@b.com"

    with pytest.raises(TokenError):
        decode_access_token(token, SECRET + "x")
    expired = create_access_token(user_id, "a@b.com", SECRET, -1)
    with pytest.raises(TokenError):
        decode_access_token(expired, SECRET)


class FakeUserRepository:
    def __init__(self, user):
        self.user = user

    async def get_by_email(self, email):
        if self.user is not None and self.user.email == email:
            return self.user
        return None


@pytest.mark.asyncio
async def test_authenticate_user():
    hashed = hash_password("secret123")
    user = SimpleNamespace(
        id=uuid4(), email="a@b.com", status="active", password_hash=hashed
    )
    repo = FakeUserRepository(user)

    assert await authenticate_user(repo, "a@b.com", "secret123") is user
    assert await authenticate_user(repo, "a@b.com", "wrong") is None
    assert await authenticate_user(FakeUserRepository(None), "a@b.com", "x") is None

    disabled = SimpleNamespace(
        id=uuid4(), email="a@b.com", status="disabled", password_hash=hashed
    )
    assert await authenticate_user(FakeUserRepository(disabled), "a@b.com", "secret123") is None
