"""persist provider request identifiers for generation recovery"""

from alembic import op
import sqlalchemy as sa

revision = "4f1a2b3c4d5e"
down_revision = "9d9f5e6a1b2c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("generation_runs", sa.Column("provider_request_id", sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column("generation_runs", "provider_request_id")