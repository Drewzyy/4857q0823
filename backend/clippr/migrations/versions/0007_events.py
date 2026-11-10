"""events: one log of what happened, which the notification service delivers

Revision ID: 0007
Revises: 0006
"""
from alembic import op
import sqlalchemy as sa

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ts", sa.DateTime(), nullable=False),
        sa.Column("category", sa.String(20), nullable=False),
        sa.Column("priority", sa.String(10), nullable=False, server_default="normal"),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        sa.Column("link", sa.Text(), nullable=True),
        sa.Column("dedupe_key", sa.String(200), nullable=True, unique=True),
        sa.Column("data", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("delivery", sa.String(10), nullable=False, server_default="none"),
        sa.Column("delivery_error", sa.Text(), nullable=True),
        sa.Column("delivered_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_events_ts", "events", ["ts"])


def downgrade() -> None:
    op.drop_index("ix_events_ts", "events")
    op.drop_table("events")
