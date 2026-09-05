"""keep generation run user ownership nullable for legacy runs"""

from alembic import op

revision = "5ab7c9d1e2f3"
down_revision = "4f1a2b3c4d5e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("generation_runs", "user_id", nullable=True)


def downgrade() -> None:
    op.alter_column("generation_runs", "user_id", nullable=False)


# This migration preserves reads of historical generation runs that predate
# user ownership backfills. New writes still set user_id at the service layer.
