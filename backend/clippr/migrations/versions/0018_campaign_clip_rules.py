"""campaigns: the rules about the video itself (length, names on screen, language, logos, focus)

Revision ID: 0018
Revises: 0017
"""
from alembic import op
import sqlalchemy as sa

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("campaigns") as t:
        t.add_column(sa.Column("clip_rules", sa.JSON(), nullable=False, server_default="{}"))


def downgrade() -> None:
    with op.batch_alter_table("campaigns") as t:
        t.drop_column("clip_rules")
