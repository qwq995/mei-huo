"""Persist staged outline planning sessions."""
from alembic import op
import sqlalchemy as sa

revision = "0009_outline_planning"
down_revision = "0008_standard_search_indexes"
branch_labels = None
depends_on = None


def upgrade():
    if "outline_planning_sessions" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table("outline_planning_sessions",
        sa.Column("project_id", sa.Text(), sa.ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("state_json", sa.Text(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False))


def downgrade():
    op.drop_table("outline_planning_sessions")
