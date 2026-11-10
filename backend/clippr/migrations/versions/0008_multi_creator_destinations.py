"""a page can take clips of several streamers

Revision ID: 0008
Revises: 0007
"""
from alembic import op
import sqlalchemy as sa

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("destination_accounts", schema=None) as b:
        b.add_column(sa.Column("creator_ids", sa.JSON(), nullable=False, server_default="[]"))
    op.execute("UPDATE destination_accounts SET creator_ids = json_array(creator_id) WHERE creator_id IS NOT NULL")


def downgrade() -> None:
    with op.batch_alter_table("destination_accounts", schema=None) as b:
        b.drop_column("creator_ids")
