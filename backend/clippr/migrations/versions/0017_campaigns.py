"""campaigns: clipping campaigns for a streamer, the clips tagged to them, and caption rules per streamer

Revision ID: 0017
Revises: 0016
"""
from alembic import op
import sqlalchemy as sa

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("creators") as t:
        t.add_column(sa.Column("caption_rules", sa.JSON(), nullable=False, server_default="{}"))
    op.create_table(
        "campaigns",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("tag", sa.String(40), nullable=False, unique=True),
        sa.Column("creator_id", sa.Integer(), sa.ForeignKey("creators.id", ondelete="SET NULL"), nullable=True),
        sa.Column("status", sa.String(10), nullable=False, server_default="live"),
        sa.Column("pool", sa.Text(), nullable=False, server_default=""),
        sa.Column("min_views", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("platforms", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("audience", sa.Text(), nullable=False, server_default=""),
        sa.Column("footage_from", sa.Date(), nullable=True),
        sa.Column("ends_at", sa.Date(), nullable=True),
        sa.Column("required_hashtags", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("must_mention", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("keywords", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("join_url", sa.Text(), nullable=False, server_default=""),
        sa.Column("discord_url", sa.Text(), nullable=False, server_default=""),
        sa.Column("guidelines_url", sa.Text(), nullable=False, server_default=""),
        sa.Column("submit_within_minutes", sa.Integer(), nullable=True),
        sa.Column("destination_ids", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("rules", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "campaign_clips",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("campaign_id", sa.Integer(), sa.ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False),
        sa.Column("clip_id", sa.Integer(), sa.ForeignKey("clips.id", ondelete="CASCADE"), nullable=False),
        sa.Column("added_by", sa.String(10), nullable=False, server_default="auto"),
        sa.Column("notified_output_ids", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("campaign_id", "clip_id"),
    )


def downgrade() -> None:
    op.drop_table("campaign_clips")
    op.drop_table("campaigns")
