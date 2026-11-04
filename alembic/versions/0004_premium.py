"""Premium: user plan and Play subscription, daily usage, device tokens and
price-alert columns on favorites.

Revision ID: 0004_premium
Revises: 0003_delete_request
Create Date: 2026-11-04
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004_premium"
down_revision: Union[str, Sequence[str], None] = "0003_delete_request"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("plan", sa.String(), nullable=False, server_default="free"))
        batch.add_column(sa.Column("plan_expires_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("play_purchase_token", sa.String(), nullable=True))
        batch.add_column(sa.Column("play_product_id", sa.String(), nullable=True))
        batch.create_index("ix_users_play_purchase_token", ["play_purchase_token"], unique=True)

    with op.batch_alter_table("favorites") as batch:
        batch.add_column(sa.Column("target_price", sa.Float(), nullable=True))
        batch.add_column(sa.Column("last_checked_price", sa.Float(), nullable=True))
        batch.add_column(sa.Column("last_checked_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("last_notified_price", sa.Float(), nullable=True))

    op.create_table(
        "usage_daily",
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("date", sa.Date(), primary_key=True),
        sa.Column("messages", sa.Integer(), nullable=False, server_default="0"),
    )

    op.create_table(
        "device_tokens",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token", sa.String(), nullable=False),
        sa.Column("platform", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_device_tokens_user_id", "device_tokens", ["user_id"])
    op.create_index("ix_device_tokens_token", "device_tokens", ["token"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_device_tokens_token", table_name="device_tokens")
    op.drop_index("ix_device_tokens_user_id", table_name="device_tokens")
    op.drop_table("device_tokens")
    op.drop_table("usage_daily")
    with op.batch_alter_table("favorites") as batch:
        batch.drop_column("last_notified_price")
        batch.drop_column("last_checked_at")
        batch.drop_column("last_checked_price")
        batch.drop_column("target_price")
    with op.batch_alter_table("users") as batch:
        batch.drop_index("ix_users_play_purchase_token")
        batch.drop_column("play_product_id")
        batch.drop_column("play_purchase_token")
        batch.drop_column("plan_expires_at")
        batch.drop_column("plan")
