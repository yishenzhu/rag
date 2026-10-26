"""Usage ledger model metadata and index tests."""

from rag.infrastructure.db.models import Base, UsageLedger
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable


def test_usage_table_and_columns():
    assert "usage_ledger" in Base.metadata.tables
    assert UsageLedger.__table__.c.period.type.length == 7
    assert UsageLedger.__table__.c.event_id.unique is True


def test_usage_indexes():
    indexes = {index.name for index in UsageLedger.__table__.indexes}
    assert {"ix_usage_tenant_period", "ix_usage_key_occurred"} <= indexes

    ddl = "\n".join(
        str(CreateIndex(index).compile(dialect=postgresql.dialect()))
        for index in UsageLedger.__table__.indexes
    )
    assert "usage_ledger (tenant_id, period, metric)" in ddl


def test_usage_ddl_compiles():
    ddl = str(
        CreateTable(UsageLedger.__table__).compile(
            dialect=postgresql.dialect()
        )
    )
    assert "CREATE TABLE usage_ledger" in ddl
    assert "ck_usage_quantity" in ddl
