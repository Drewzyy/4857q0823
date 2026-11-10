"""jobs report progress, so the watchdog only stops jobs that went quiet

Revision ID: 0013
Revises: 0012
"""
from alembic import op
import sqlalchemy as sa

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("jobs", schema=None) as b:
        b.add_column(sa.Column("heartbeat_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("jobs", schema=None) as b:
        b.drop_column("heartbeat_at")
