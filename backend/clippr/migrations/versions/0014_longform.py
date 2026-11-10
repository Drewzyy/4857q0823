"""long-form videos to find clips in

Revision ID: 0014
Revises: 0013
"""
from alembic import op
import sqlalchemy as sa

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "longform_videos",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("file_path", sa.Text(), nullable=True),
        sa.Column("title", sa.Text(), nullable=False, server_default=""),
        sa.Column("creator_id", sa.Integer(), sa.ForeignKey("creators.id", ondelete="SET NULL"), nullable=True),
        sa.Column("clips_wanted", sa.Integer(), nullable=False, server_default="6"),
        sa.Column("status", sa.String(16), nullable=False, server_default="new"),
        sa.Column("status_detail", sa.Text(), nullable=False, server_default=""),
        sa.Column("duration", sa.Float(), nullable=True),
        sa.Column("moments", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    with op.batch_alter_table("clips", schema=None) as b:
        b.add_column(sa.Column("longform_id", sa.Integer(), nullable=True))
        b.create_foreign_key("fk_clips_longform", "longform_videos", ["longform_id"], ["id"], ondelete="SET NULL")


def downgrade() -> None:
    with op.batch_alter_table("clips", schema=None) as b:
        b.drop_constraint("fk_clips_longform", type_="foreignkey")
        b.drop_column("longform_id")
    op.drop_table("longform_videos")
