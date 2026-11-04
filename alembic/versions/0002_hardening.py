"""Hardening: token_version, timestamps, message products, favorite currency
and a unique (user_id, link) constraint on favorites.

Revision ID: 0002_hardening
Revises: 0001_baseline
Create Date: 2026-11-03
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002_hardening"
down_revision: Union[str, Sequence[str], None] = "0001_baseline"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("token_version", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("created_at", sa.DateTime(), nullable=True))
        batch.create_index("ix_users_reset_token", ["reset_token"])
    # Reset tokens are now stored hashed; any outstanding raw tokens are void.
    op.execute("UPDATE users SET reset_token = NULL, reset_token_expires = NULL")

    with op.batch_alter_table("chat_messages") as batch:
        batch.add_column(sa.Column("products", sa.Text(), nullable=True))
        batch.create_index("ix_chat_messages_session_id", ["session_id"])

    with op.batch_alter_table("chat_sessions") as batch:
        batch.create_index("ix_chat_sessions_user_id", ["user_id"])

    # Drop duplicate favorites (keep the oldest) before adding the constraint.
    op.execute(
        """
        DELETE FROM favorites
        WHERE id NOT IN (
            SELECT MIN(id) FROM favorites GROUP BY user_id, link
        )
        """
    )
    with op.batch_alter_table("favorites") as batch:
        batch.add_column(sa.Column("currency", sa.String(), nullable=True))
        batch.add_column(sa.Column("created_at", sa.DateTime(), nullable=True))
        batch.create_index("ix_favorites_user_id", ["user_id"])
        batch.create_unique_constraint("uq_favorites_user_link", ["user_id", "link"])


def downgrade() -> None:
    with op.batch_alter_table("favorites") as batch:
        batch.drop_constraint("uq_favorites_user_link", type_="unique")
        batch.drop_index("ix_favorites_user_id")
        batch.drop_column("created_at")
        batch.drop_column("currency")
    with op.batch_alter_table("chat_sessions") as batch:
        batch.drop_index("ix_chat_sessions_user_id")
    with op.batch_alter_table("chat_messages") as batch:
        batch.drop_index("ix_chat_messages_session_id")
        batch.drop_column("products")
    with op.batch_alter_table("users") as batch:
        batch.drop_index("ix_users_reset_token")
        batch.drop_column("created_at")
        batch.drop_column("token_version")
