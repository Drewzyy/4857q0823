"""post links and metric snapshots for analytics

Revision ID: 0005
Revises: 0004
"""
from alembic import op
import sqlalchemy as sa
import clippr.models

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("clip_outputs", schema=None) as b:
        b.add_column(sa.Column("post_url", sa.Text(), nullable=True))
    op.create_table(
        "metric_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("output_id", sa.Integer(), sa.ForeignKey("clip_outputs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("ts", clippr.models.UTCDateTime(), nullable=False),
        sa.Column("views", sa.Integer(), nullable=True),
        sa.Column("likes", sa.Integer(), nullable=True),
        sa.Column("comments", sa.Integer(), nullable=True),
        sa.Column("shares", sa.Integer(), nullable=True),
        sa.Column("source", sa.String(length=10), nullable=False),
    )
    op.create_index("ix_metric_snapshots_output_id", "metric_snapshots", ["output_id"])


def downgrade() -> None:
    op.drop_index("ix_metric_snapshots_output_id", "metric_snapshots")
    op.drop_table("metric_snapshots")
    with op.batch_alter_table("clip_outputs", schema=None) as b:
        b.drop_column("post_url")
