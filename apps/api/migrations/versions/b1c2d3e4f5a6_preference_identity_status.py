"""add stable preference identity and mutation status"""

import sqlalchemy as sa
from alembic import op

revision = "b1c2d3e4f5a6"
down_revision = "a8b9c0d1e2f3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("preference_events", sa.Column("preference_id", sa.String(64), nullable=True))
    op.add_column("preference_events", sa.Column("status", sa.String(16), nullable=False, server_default="active"))
    op.create_index("ix_preference_events_preference_id", "preference_events", ["preference_id"])
    op.execute("UPDATE preference_events SET preference_id = id WHERE preference_id IS NULL")


def downgrade() -> None:
    op.drop_index("ix_preference_events_preference_id", table_name="preference_events")
    op.drop_column("preference_events", "status")
    op.drop_column("preference_events", "preference_id")
