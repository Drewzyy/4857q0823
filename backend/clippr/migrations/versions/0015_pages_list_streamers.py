"""pages take only the streamers linked to them

A page with no streamers listed used to take everyone's clips. Now a page lists exactly whose clips it gets,
so each such page is given every current streamer: it keeps getting what it got before.

Revision ID: 0015
Revises: 0014
"""
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        UPDATE destination_accounts
        SET creator_ids = (SELECT json_group_array(id) FROM creators),
            creator_id = (SELECT min(id) FROM creators)
        WHERE (creator_ids IS NULL OR json_array_length(creator_ids) = 0) AND creator_id IS NULL
          AND EXISTS (SELECT 1 FROM creators)
    """)


def downgrade() -> None:
    pass  # the lists stay; older versions read them the same way for pages that have streamers
