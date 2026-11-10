"""each clip's grade (S to D) and why

Revision ID: 0012
Revises: 0011
"""
from alembic import op
import sqlalchemy as sa

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("clips", schema=None) as b:
        b.add_column(sa.Column("grade", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("clips", schema=None) as b:
        b.drop_column("grade")
