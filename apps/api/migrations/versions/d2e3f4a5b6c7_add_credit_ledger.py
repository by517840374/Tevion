"""add auditable credit accounts, ledger and reservations

Revision ID: d2e3f4a5b6c7
Revises: c7e8f9a0b1c2
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d2e3f4a5b6c7"
down_revision: Union[str, None] = "c7e8f9a0b1c2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "credit_accounts",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("user_id", sa.String(length=64), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("balance_points", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("user_id"),
    )
    op.create_table(
        "credit_ledger",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("account_id", sa.String(length=64), sa.ForeignKey("credit_accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("delta_points", sa.Integer(), nullable=False),
        sa.Column("entry_type", sa.String(length=32), nullable=False),
        sa.Column("reference_id", sa.String(length=128), nullable=False),
        sa.Column("reason", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("reference_id"),
    )
    op.create_table(
        "credit_reservations",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("account_id", sa.String(length=64), sa.ForeignKey("credit_accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("generation_run_id", sa.String(length=64), sa.ForeignKey("generation_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("points", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="reserved"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("settled_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("generation_run_id"),
    )


def downgrade() -> None:
    op.drop_table("credit_reservations")
    op.drop_table("credit_ledger")
    op.drop_table("credit_accounts")
