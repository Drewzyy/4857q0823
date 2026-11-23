"""proof a post is real: each recorded post link is opened and checked (live, on the right page)

Revision ID: 0022
Revises: 0021
"""
import sqlalchemy as sa
from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("clip_outputs") as t:
        t.add_column(sa.Column("post_check", sa.JSON(), nullable=True))


def downgrade() -> None:
    pass  # older versions ignore it
