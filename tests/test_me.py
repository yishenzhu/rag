"""JWT-protected /v1/me tests."""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from rag.app.auth_routes import me
from rag.app.deps import require_user
from rag.app.main import create_app
from rag.conf import get_settings
from rag.security.auth import create_access_token


def make_request(token):
    headers = {} if token is None else {"authorization": f"Bearer {token}"}
    return SimpleNamespace(headers=headers)


class FakeSession:
    def __init__(self, user):
        self.user = user

    async def get(self, model, user_id):
        return self.user


@pytest.mark.asyncio
async def test_require_user_and_me():
    user = SimpleNamespace(id=uuid4(), email="a@b.com", status="active")
    token = create_access_token(user.id, user.email, get_settings().jwt_secret, 60)
    assert await require_user(make_request(token), FakeSession(user)) is user

    response = await me(user)
    assert (response.id, response.email) == (user.id, user.email)


@pytest.mark.asyncio
async def test_require_user_rejects_invalid_tokens():
    with pytest.raises(HTTPException):
        await require_user(make_request(None), FakeSession(None))
    with pytest.raises(HTTPException):
        await require_user(make_request("not-a-token"), FakeSession(None))

    disabled = SimpleNamespace(id=uuid4(), email="a@b.com", status="disabled")
    token = create_access_token(
        disabled.id, disabled.email, get_settings().jwt_secret, 60
    )
    with pytest.raises(HTTPException):
        await require_user(make_request(token), FakeSession(disabled))


def test_me_route_registered():
    paths = create_app().openapi()["paths"]
    assert "/v1/me" in paths
