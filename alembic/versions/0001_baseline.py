"""Baseline: schema as previously created by Base.metadata.create_all().

Existing databases are stamped at this revision automatically by
`python -m app.db.migrate` (see app/db/migrate.py).

Revision ID: 0001_baseline
Revises:
Create Date: 2026-11-03
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001_baseline"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("hashed_password", sa.String(), nullable=False),
        sa.Column("full_name", sa.String(), nullable=True),
        sa.Column("language", sa.String(), nullable=True),
        sa.Column("currency", sa.String(), nullable=True),
        sa.Column("reset_token", sa.String(), nullable=True),
        sa.Column("reset_token_expires", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_users_id", "users", ["id"])
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "chat_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("title", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_chat_sessions_id", "chat_sessions", ["id"])

    op.create_table(
        "chat_messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("session_id", sa.Integer(), sa.ForeignKey("chat_sessions.id"), nullable=False),
        sa.Column("role", sa.String(), nullable=True),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_chat_messages_id", "chat_messages", ["id"])

    op.create_table(
        "favorites",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(), nullable=True),
        sa.Column("price", sa.Float(), nullable=True),
        sa.Column("source", sa.String(), nullable=True),
        sa.Column("link", sa.String(), nullable=True),
        sa.Column("thumbnail", sa.String(), nullable=True),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id"), nullable=True),
    )
    op.create_index("ix_favorites_id", "favorites", ["id"])
    op.create_index("ix_favorites_title", "favorites", ["title"])


def downgrade() -> None:
    op.drop_table("favorites")
    op.drop_table("chat_messages")
    op.drop_table("chat_sessions")
    op.drop_table("users")
