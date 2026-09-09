"""add nullable local password hash

Revision ID: c7e8f9a0b1c2
Revises: b1c2d3e4f5a6
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c7e8f9a0b1c2"
down_revision: Union[str, None] = "b1c2d3e4f5a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("password_hash", sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "password_hash")
