"""API key create/list tests (fake session, no database)."""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from rag.app.api_key_routes import (
    CreateApiKeyRequest,
    create_api_key,
    list_api_keys,
    revoke_api_key,
)
from rag.app.deps import UserPrincipal, require_role
from rag.infrastructure.db.models import ApiKey


class FakeResult:
    def __init__(self, one=None, many=None):
        self.one, self.many = one, many or []

    def scalar_one_or_none(self):
        return self.one

    def scalars(self):
        return self

    def all(self):
        return self.many


class FakeSession:
    def __init__(self, project=None, many=None, one=None):
        self.project = project
        self.many = many
        self.one = one
        self.added = []
        self.committed = False

    async def get(self, model, object_id):
        return self.project

    async def execute(self, stmt):
        return FakeResult(self.one, self.many)

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.committed = True

    async def rollback(self):
        pass


def make_principal(role="owner"):
    return UserPrincipal(uuid4(), "a@b.com", uuid4(), role)


@pytest.mark.asyncio
async def test_create_and_list_api_key():
    principal = make_principal()
    project = SimpleNamespace(id=uuid4(), tenant_id=principal.tenant_id)
    session = FakeSession(project=project)
    response = await create_api_key(
        CreateApiKeyRequest(
            name="prod", project_id=project.id, scopes=["memories:read"]
        ),
        principal,
        session,
    )
    record = session.added[0]
    assert isinstance(record, ApiKey)
    assert (record.tenant_id, record.project_id, record.scopes) == (
        principal.tenant_id, project.id, ["memories:read"]
    )
    assert response.key.startswith(response.key_prefix + "_")
    assert session.committed
    listed = await list_api_keys(principal, FakeSession(many=[record]), None)
    assert (listed[0].id, listed[0].key_prefix) == (record.id, record.key_prefix)


@pytest.mark.asyncio
async def test_revoke_api_key():
    principal = make_principal()
    record = SimpleNamespace(id=uuid4(), status="active", revoked_at=None)
    session = FakeSession(one=record)
    await revoke_api_key(record.id, principal, session)

    assert record.status == "revoked" and record.revoked_at is not None
    assert session.committed

    with pytest.raises(HTTPException) as exc:
        await revoke_api_key(uuid4(), principal, FakeSession(one=None))
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_require_role():
    dependency = require_role("owner", "admin")
    with pytest.raises(HTTPException) as exc:
        await dependency(make_principal("member"))
    assert exc.value.status_code == 403
    owner = make_principal("owner")
    assert await dependency(owner) is owner
