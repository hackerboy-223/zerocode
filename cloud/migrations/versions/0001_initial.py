"""Create the initial ZeroCode Cloud schema."""

from alembic import op

from app import models  # noqa: F401
from app.database import Base

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Keep this baseline migration stable: request_leases is introduced by 0002.
    tables = [table for table in Base.metadata.sorted_tables if table.name != "request_leases"]
    Base.metadata.create_all(bind=op.get_bind(), tables=tables)


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind())
