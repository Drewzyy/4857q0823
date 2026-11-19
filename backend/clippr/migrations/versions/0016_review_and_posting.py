"""review, safety and posting: what Muse (or you) decided about each page's video, and where Postiz took it

- creators.content_kind: regular | gaming | podcast, used to route clips to the right pages
- clips.safety: the pre-post safety check (status, flagged categories, reasons, timestamps)
- clip_outputs: review state, reviewer's note, schedule, and the Postiz post id / state / URL / error

Revision ID: 0016
Revises: 0015
"""
import sqlalchemy as sa
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("creators") as t:
        t.add_column(sa.Column("content_kind", sa.String(16), nullable=False, server_default="regular"))
    with op.batch_alter_table("clips") as t:
        t.add_column(sa.Column("safety", sa.JSON(), nullable=True))
    with op.batch_alter_table("clip_outputs") as t:
        t.add_column(sa.Column("review", sa.String(16), nullable=False, server_default="pending"))  # pending | approved | rejected
        t.add_column(sa.Column("review_note", sa.Text(), nullable=False, server_default=""))
        t.add_column(sa.Column("reviewed_by", sa.String(40), nullable=False, server_default=""))
        t.add_column(sa.Column("scheduled_at", sa.DateTime(), nullable=True))
        t.add_column(sa.Column("postiz_post_id", sa.String(80), nullable=True))
        t.add_column(sa.Column("postiz_state", sa.String(24), nullable=True))  # draft | queued | published | error
        t.add_column(sa.Column("postiz_error", sa.Text(), nullable=True))


def downgrade() -> None:
    pass  # new columns are ignored by older versions
