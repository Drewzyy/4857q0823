"""Dropbox auto-upload: each finished video file and its verified copy in Dropbox

Revision ID: 0021
Revises: 0020
"""
import sqlalchemy as sa
from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "dropbox_uploads",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("local_path", sa.Text(), nullable=False, unique=True),
        sa.Column("output_id", sa.Integer(), sa.ForeignKey("clip_outputs.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("status", sa.String(12), nullable=False, server_default="queued"),
        sa.Column("dropbox_path", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_try_at", sa.DateTime(), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("content_hash", sa.String(64), nullable=True),
        sa.Column("session_id", sa.Text(), nullable=True),
        sa.Column("session_offset", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("uploaded_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("dropbox_uploads")
