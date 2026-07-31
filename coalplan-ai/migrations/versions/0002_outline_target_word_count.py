"""add outline target word count

Revision ID: 0002_outline_target_word_count
Revises: 0001_initial_workspace
Create Date: 2026-06-21
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0002_outline_target_word_count"
down_revision = "0001_initial_workspace"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {item["name"] for item in sa.inspect(op.get_bind()).get_columns("project_outline_nodes")}
    if "target_word_count" not in columns:
        op.add_column("project_outline_nodes", sa.Column("target_word_count", sa.Integer(), nullable=True))


def downgrade() -> None:
    columns = {item["name"] for item in sa.inspect(op.get_bind()).get_columns("project_outline_nodes")}
    if "target_word_count" in columns:
        op.drop_column("project_outline_nodes", "target_word_count")
