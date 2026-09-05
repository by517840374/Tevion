"""add bounded generation execution lease fields"""

from alembic import op
import sqlalchemy as sa

revision = "84a1b2c3d4e5"
down_revision = "6c7d8e9f0a1b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("generation_runs", sa.Column("lease_owner", sa.String(length=120), nullable=True))
    op.add_column("generation_runs", sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("generation_runs", "lease_expires_at")
    op.drop_column("generation_runs", "lease_owner")
