"""the quality check on each finished video (size, length, sound, black or frozen picture, loudness)

Revision ID: 0020
Revises: 0019
"""
import sqlalchemy as sa
from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("clip_outputs") as t:
        t.add_column(sa.Column("quality", sa.JSON(), nullable=True))


def downgrade() -> None:
    pass  # older versions ignore it
