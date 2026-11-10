"""pages pick their streamers, so the hand-wired funnel routes go

Revision ID: 0010
Revises: 0009
"""
from alembic import op
import sqlalchemy as sa

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # A page that only had routes from some streamers' accounts now takes exactly those streamers.
    op.execute("""
        UPDATE destination_accounts SET creator_ids = (
            SELECT json_group_array(DISTINCT j.value) FROM funnel_routes r
            JOIN source_accounts sa ON sa.id = r.source_id, json_each(sa.creator_ids) j
            WHERE r.destination_id = destination_accounts.id AND r.enabled = 1)
        WHERE json_array_length(creator_ids) = 0
          AND EXISTS (SELECT 1 FROM funnel_routes r JOIN source_accounts sa ON sa.id = r.source_id
                      WHERE r.destination_id = destination_accounts.id AND r.enabled = 1 AND json_array_length(sa.creator_ids) > 0)
    """)
    # A page nothing was routed to got no clips; with no streamers listed it would now take everyone's, so it's
    # paused instead (the user turns it back on under Destinations).
    op.execute("""
        UPDATE destination_accounts SET enabled = 0
        WHERE json_array_length(creator_ids) = 0
          AND NOT EXISTS (SELECT 1 FROM funnel_routes r WHERE r.destination_id = destination_accounts.id AND r.enabled = 1)
    """)
    op.drop_table("funnel_routes")
    op.execute("DELETE FROM settings WHERE key = 'funnel_layout'")


def downgrade() -> None:
    op.create_table(
        "funnel_routes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_id", sa.Integer(), sa.ForeignKey("source_accounts.id", ondelete="CASCADE")),
        sa.Column("destination_id", sa.Integer(), sa.ForeignKey("destination_accounts.id", ondelete="CASCADE")),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("allow_cross_creator", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
