"""Registration tests (fake session, no database)."""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from rag.app.auth_routes import RegisterRequest, register
from rag.conf import get_settings
from rag.infrastructure.db.models import Membership, Project, Tenant, User
from rag.security.auth import decode_access_token


class FakeResult:
    def __init__(self, user):
        self.user = user

    def scalar_one_or_none(self):
        return self.user


class FakeSession:
    def __init__(self, existing_user=None):
        self.existing_user = existing_user
        self.added = []
        self.events = []
        self.committed = False

    async def execute(self, stmt):
        return FakeResult(self.existing_user)

    def add_all(self, objects):
        self.added.extend(objects)
        self.events.extend(type(obj).__name__ for obj in objects)

    async def flush(self):
        self.events.append("flush")

    async def commit(self):
        self.committed = True
        self.events.append("commit")

    async def rollback(self):
        pass


@pytest.mark.asyncio
async def test_register_creates_user_tenant_membership_project():
    session = FakeSession()
    response = await register(
        RegisterRequest(email="A@B.com", password="secret123", tenant_name="Acme"),
        session,
    )

    assert session.committed
    assert {type(obj) for obj in session.added} == {User, Tenant, Membership, Project}
    user = next(obj for obj in session.added if isinstance(obj, User))
    tenant = next(obj for obj in session.added if isinstance(obj, Tenant))
    membership = next(obj for obj in session.added if isinstance(obj, Membership))
    project = next(obj for obj in session.added if isinstance(obj, Project))

    assert user.email == "a@b.com"
    assert tenant.slug.startswith("acme-")
    assert membership.role == "owner"
    assert project.slug == "default"
    assert project.tenant_id == tenant.id

    payload = decode_access_token(response.access_token, get_settings().jwt_secret)
    assert (payload.user_id, payload.tenant_id, payload.role) == (
        response.user_id,
        response.tenant_id,
        "owner",
    )


@pytest.mark.asyncio
async def test_register_rejects_duplicate_email():
    session = FakeSession(existing_user=SimpleNamespace(id=uuid4()))
    with pytest.raises(HTTPException) as exc:
        await register(
            RegisterRequest(email="a@b.com", password="secret123", tenant_name="Acme"),
            session,
        )

    assert exc.value.status_code == 409
    assert not session.added


@pytest.mark.asyncio
async def test_register_flushes_parent_rows_before_children():
    session = FakeSession()
    await register(
        RegisterRequest(email="a@b.com", password="secret123", tenant_name="Acme"),
        session,
    )

    assert session.events == [
        "User",
        "Tenant",
        "flush",
        "Membership",
        "Project",
        "commit",
    ]
