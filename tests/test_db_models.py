"""ORM model metadata and offline DDL tests (no live database required)."""

from rag.infrastructure.db.models import (
    ApiKey,
    Base,
    Membership,
    Project,
    Tenant,
    User,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.schema import CreateTable


def test_tables_registered():
    assert set(Base.metadata.tables) == {
        "tenants",
        "users",
        "memberships",
        "projects",
        "api_keys",
    }


def test_membership_composite_key():
    assert list(Membership.__table__.primary_key.columns.keys()) == [
        "tenant_id",
        "user_id",
    ]


def test_postgres_types_and_unique_key():
    assert isinstance(Project.__table__.c.settings.type, JSONB)
    assert isinstance(ApiKey.__table__.c.scopes.type, ARRAY)
    assert ApiKey.__table__.c.key_prefix.unique is True


def test_constraints_are_named():
    project_constraints = {c.name for c in Project.__table__.constraints}
    assert "uq_projects_tenant_slug" in project_constraints

    membership_constraints = {c.name for c in Membership.__table__.constraints}
    assert "ck_memberships_role" in membership_constraints

    api_key_constraints = {c.name for c in ApiKey.__table__.constraints}
    assert "ck_api_keys_status" in api_key_constraints


def test_ddl_compiles_for_postgres():
    ddl = "\n".join(
        str(CreateTable(table.__table__).compile(dialect=postgresql.dialect()))
        for table in (Tenant, User, Membership, Project, ApiKey)
    )
    assert "JSONB" in ddl
    assert "gen_random_uuid()" in ddl
    assert "VARCHAR[]" in ddl
