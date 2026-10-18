"""database object store

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-18 09:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "stored_objects",
        sa.Column("key", sa.String(length=512), nullable=False),
        sa.Column("content_type", sa.String(length=200), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_stored_objects")),
    )
    op.create_table(
        "stored_object_chunks",
        sa.Column("key", sa.String(length=512), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.ForeignKeyConstraint(
            ["key"],
            ["stored_objects.key"],
            name=op.f("fk_stored_object_chunks_key_stored_objects"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("key", "seq", name=op.f("pk_stored_object_chunks")),
    )


def downgrade() -> None:
    op.drop_table("stored_object_chunks")
    op.drop_table("stored_objects")
