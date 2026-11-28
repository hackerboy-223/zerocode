"""Add persistent login throttling state."""

import sqlalchemy as sa
from alembic import op

revision = "0003_login_attempts"
down_revision = "0002_request_leases"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "login_attempts" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "login_attempts",
        sa.Column("key_hash", sa.String(length=64), primary_key=True),
        sa.Column("window_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("blocked_until", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    if "login_attempts" in sa.inspect(op.get_bind()).get_table_names():
        op.drop_table("login_attempts")
