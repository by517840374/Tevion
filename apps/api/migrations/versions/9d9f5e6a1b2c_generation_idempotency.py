"""generation idempotency claim fields"""
from alembic import op
import sqlalchemy as sa

revision = "9d9f5e6a1b2c"
down_revision = "78cc1e16a72a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("generation_runs", sa.Column("user_id", sa.String(length=64), nullable=True))
    op.add_column("generation_runs", sa.Column("idempotency_key", sa.String(length=255), nullable=True))
    op.add_column("generation_runs", sa.Column("request_fingerprint", sa.String(length=64), nullable=True))
    op.execute("UPDATE generation_runs SET user_id = (SELECT projects.user_id FROM projects JOIN sessions ON sessions.project_id = projects.id WHERE sessions.id = generation_runs.session_id)")
    op.create_foreign_key("fk_generation_runs_user_id", "generation_runs", "users", ["user_id"], ["id"], ondelete="CASCADE")
    op.create_unique_constraint("uq_generation_runs_idempotency", "generation_runs", ["user_id", "session_id", "idempotency_key"])


def downgrade() -> None:
    op.drop_constraint("uq_generation_runs_idempotency", "generation_runs", type_="unique")
    op.drop_constraint("fk_generation_runs_user_id", "generation_runs", type_="foreignkey")
    op.drop_column("generation_runs", "request_fingerprint")
    op.drop_column("generation_runs", "idempotency_key")
    op.drop_column("generation_runs", "user_id")