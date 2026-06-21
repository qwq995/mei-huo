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
    op.add_column("project_outline_nodes", sa.Column("target_word_count", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("project_outline_nodes", "target_word_count")
