"""add nullable recovery phase and reconciliation fields to generation runs"""

from alembic import op
import sqlalchemy as sa

revision = "6c7d8e9f0a1b"
down_revision = "5ab7c9d1e2f3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("generation_runs", sa.Column("phase", sa.String(length=32), nullable=True))
    op.add_column("generation_runs", sa.Column("last_polled_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("generation_runs", sa.Column("next_poll_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("generation_runs", sa.Column("reconciliation_required", sa.Boolean(), nullable=True))
    op.add_column("generation_runs", sa.Column("reconciliation_reason", sa.String(length=255), nullable=True))
    op.add_column("generation_runs", sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("generation_runs", "finalized_at")
    op.drop_column("generation_runs", "reconciliation_reason")
    op.drop_column("generation_runs", "reconciliation_required")
    op.drop_column("generation_runs", "next_poll_at")
    op.drop_column("generation_runs", "last_polled_at")
    op.drop_column("generation_runs", "phase")
