"""where each streamer's facecam sits, for the stacked layout

Revision ID: 0009
Revises: 0008
"""
from alembic import op
import sqlalchemy as sa

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("creators", schema=None) as b:
        b.add_column(sa.Column("facecam", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("creators", schema=None) as b:
        b.drop_column("facecam")
