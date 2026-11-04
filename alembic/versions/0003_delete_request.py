"""Account deletion requests from the web: hashed delete token and expiry.

Revision ID: 0003_delete_request
Revises: 0002_hardening
Create Date: 2026-11-04
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003_delete_request"
down_revision: Union[str, Sequence[str], None] = "0002_hardening"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("delete_token", sa.String(), nullable=True))
        batch.add_column(sa.Column("delete_token_expires", sa.DateTime(), nullable=True))
        batch.create_index("ix_users_delete_token", ["delete_token"])


def downgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.drop_index("ix_users_delete_token")
        batch.drop_column("delete_token_expires")
        batch.drop_column("delete_token")
