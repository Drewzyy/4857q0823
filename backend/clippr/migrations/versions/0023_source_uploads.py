"""YouTube channels: new full videos and past streams are made into clips (long-form)

Revision ID: 0023
Revises: 0022
"""
import sqlalchemy as sa
from alembic import op

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("source_accounts") as t:
        t.add_column(sa.Column("clip_uploads", sa.Boolean(), nullable=False, server_default=sa.true()))
        t.add_column(sa.Column("seen_uploads", sa.JSON(), nullable=True))


def downgrade() -> None:
    pass  # older versions ignore them
