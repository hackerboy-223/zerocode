"""Add persistent request leases for abuse protection."""

from alembic import op
import sqlalchemy as sa

revision = "0002_request_leases"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "request_leases",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("device_id", sa.String(length=36), sa.ForeignKey("devices.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_request_leases_user_id", "request_leases", ["user_id"])
    op.create_index("ix_request_leases_device_id", "request_leases", ["device_id"])
    op.create_index("ix_request_leases_created_at", "request_leases", ["created_at"])
    op.create_index("ix_request_leases_expires_at", "request_leases", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_request_leases_expires_at", table_name="request_leases")
    op.drop_index("ix_request_leases_created_at", table_name="request_leases")
    op.drop_index("ix_request_leases_device_id", table_name="request_leases")
    op.drop_index("ix_request_leases_user_id", table_name="request_leases")
    op.drop_table("request_leases")
