"""add usage ledger

Revision ID: 0004_add_usage_ledger
Revises: 0003_add_outbox
Create Date: 2026-10-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_add_usage_ledger"
down_revision: str | Sequence[str] | None = "0003_add_outbox"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "usage_ledger",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("api_key_id", sa.Uuid()),
        sa.Column("metric", sa.String(length=32), nullable=False),
        sa.Column(
            "quantity", sa.BigInteger(), server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("model", sa.String(length=128)),
        sa.Column("period", sa.String(length=7), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.CheckConstraint("quantity >= 0", name="ck_usage_quantity"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["api_key_id"], ["api_keys.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id"),
    )
    op.create_index(
        "ix_usage_tenant_period",
        "usage_ledger",
        ["tenant_id", "period", "metric"],
    )
    op.create_index(
        "ix_usage_key_occurred",
        "usage_ledger",
        ["api_key_id", "occurred_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_usage_key_occurred", table_name="usage_ledger")
    op.drop_index("ix_usage_tenant_period", table_name="usage_ledger")
    op.drop_table("usage_ledger")
