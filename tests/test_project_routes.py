"""Project route tests (fake session, no database)."""

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from rag.app.deps import UserPrincipal
from rag.app.project_routes import CreateProjectRequest, create_project, list_projects
from sqlalchemy.exc import IntegrityError


class FakeResult:
    def __init__(self, many=None):
        self.many = many or []

    def scalars(self):
        return self

    def all(self):
        return self.many


class FakeSession:
    def __init__(self, many=None, fail_commit=False):
        self.many = many
        self.fail_commit = fail_commit
        self.added = []
        self.committed = False
        self.rolled_back = False

    async def execute(self, stmt):
        return FakeResult(self.many)

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        if self.fail_commit:
            raise IntegrityError("stmt", {}, Exception("duplicate"))
        self.committed = True

    async def rollback(self):
        self.rolled_back = True


def make_principal(role="owner"):
    return UserPrincipal(uuid4(), "a@b.com", uuid4(), role)


@pytest.mark.asyncio
async def test_create_and_list_project():
    principal = make_principal()
    session = FakeSession()
    response = await create_project(
        CreateProjectRequest(name="Analytics"), principal, session
    )

    project = session.added[0]
    assert project.tenant_id == principal.tenant_id
    assert project.slug.startswith("analytics-")
    assert response.slug == project.slug
    assert session.committed

    record = SimpleNamespace(
        id=project.id,
        name=project.name,
        slug=project.slug,
        settings={},
        created_at=datetime.now(UTC),
    )
    listed = await list_projects(principal, FakeSession(many=[record]))
    assert (listed[0].id, listed[0].slug) == (record.id, record.slug)


@pytest.mark.asyncio
async def test_create_project_accepts_explicit_slug():
    principal = make_principal()
    session = FakeSession()
    response = await create_project(
        CreateProjectRequest(name="Analytics", slug="analytics"), principal, session
    )
    assert response.slug == "analytics"


@pytest.mark.asyncio
async def test_create_project_rejects_duplicate_slug():
    session = FakeSession(fail_commit=True)
    with pytest.raises(HTTPException) as exc:
        await create_project(
            CreateProjectRequest(name="Analytics", slug="dup"),
            make_principal(),
            session,
        )
    assert exc.value.status_code == 409
    assert session.rolled_back
