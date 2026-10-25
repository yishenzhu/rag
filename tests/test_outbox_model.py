"""Outbox model metadata and partial index tests."""

from rag.infrastructure.db.models import Base, OutboxEvent
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.schema import CreateIndex, CreateTable


def test_outbox_table_and_payload():
    assert "outbox" in Base.metadata.tables
    assert isinstance(OutboxEvent.__table__.c.payload.type, JSONB)


def test_outbox_pending_index():
    indexes = {index.name: index for index in OutboxEvent.__table__.indexes}
    assert "ix_outbox_pending" in indexes

    ddl = "\n".join(
        str(CreateIndex(index).compile(dialect=postgresql.dialect()))
        for index in OutboxEvent.__table__.indexes
    )
    assert "WHERE status = 'pending'" in ddl


def test_outbox_ddl_compiles():
    ddl = str(
        CreateTable(OutboxEvent.__table__).compile(
            dialect=postgresql.dialect()
        )
    )
    assert "CREATE TABLE outbox" in ddl
    assert "BIGSERIAL" in ddl or "BIGINT" in ddl
    assert "JSONB" in ddl
