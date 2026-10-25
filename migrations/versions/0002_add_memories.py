"""add memories

Revision ID: 0002_add_memories
Revises: 0001_initial
Create Date: 2026-10-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_add_memories"
down_revision: str | Sequence[str] | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "memories",
        sa.Column(
            "id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("external_id", sa.String(length=255)),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "metadata", postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"), nullable=False,
        ),
        sa.Column(
            "status", sa.String(length=16), server_default=sa.text("'active'"),
            nullable=False,
        ),
        sa.Column("source", sa.String(length=64)),
        sa.Column("embedding_model", sa.String(length=128)),
        sa.Column("qdrant_point_id", sa.Uuid()),
        sa.Column(
            "importance", sa.Float(), server_default=sa.text("0.5"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "status IN ('pending', 'active', 'failed', 'deleted', 'expired')",
            name="ck_memories_status",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_memories_tenant_project_created",
        "memories",
        ["tenant_id", "project_id", "created_at"],
    )
    op.create_index(
        "uq_memories_project_content",
        "memories",
        ["project_id", "content_hash"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_memories_external",
        "memories",
        ["project_id", "external_id"],
        postgresql_where=sa.text("external_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_memories_external", table_name="memories")
    op.drop_index("uq_memories_project_content", table_name="memories")
    op.drop_index("ix_memories_tenant_project_created", table_name="memories")
    op.drop_table("memories")
