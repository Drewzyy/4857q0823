"""what kind of clip each one is, and Postiz gone

- clips.content: the detected kind (gaming, podcast, irl, chatting) with how sure and why (content.py)
- clip_outputs: the Postiz columns go; Muse posts and reports where with mark_posted

Revision ID: 0019
Revises: 0018
"""
import sqlalchemy as sa
from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("clips") as t:
        t.add_column(sa.Column("content", sa.JSON(), nullable=True))
    with op.batch_alter_table("clip_outputs") as t:
        t.drop_column("postiz_post_id")
        t.drop_column("postiz_state")
        t.drop_column("postiz_error")


def downgrade() -> None:
    pass  # older versions ignore the new column; the Postiz ones aren't coming back
