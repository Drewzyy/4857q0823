"""a clipping account can cover several streamers

Revision ID: 0004
Revises: 0003
"""
from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("source_accounts", schema=None) as b:
        b.add_column(sa.Column("creator_ids", sa.JSON(), nullable=False, server_default="[]"))
    op.execute("UPDATE source_accounts SET creator_ids = json_array(creator_id) WHERE creator_id IS NOT NULL")


def downgrade() -> None:
    with op.batch_alter_table("source_accounts", schema=None) as b:
        b.drop_column("creator_ids")
