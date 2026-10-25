"""Memory model metadata and index tests."""

from rag.infrastructure.db.models import Base, Memory
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.schema import CreateIndex, CreateTable


def test_memory_table_and_columns():
    assert "memories" in Base.metadata.tables
    assert isinstance(Memory.__table__.c["metadata"].type, JSONB)
    assert Memory.__table__.c["content_hash"].type.length == 64


def test_memory_partial_indexes():
    indexes = {index.name: index for index in Memory.__table__.indexes}
    assert indexes["uq_memories_project_content"].unique is True

    ddl = "\n".join(
        str(CreateIndex(index).compile(dialect=postgresql.dialect()))
        for index in Memory.__table__.indexes
    )
    assert "WHERE deleted_at IS NULL" in ddl
    assert "WHERE external_id IS NOT NULL" in ddl


def test_memory_ddl_compiles():
    ddl = str(CreateTable(Memory.__table__).compile(dialect=postgresql.dialect()))
    assert "CREATE TABLE memories" in ddl
    assert "JSONB" in ddl
