"""add persistent generation jobs

Revision ID: 0005_generation_jobs
Revises: 0004_outline_context_and_skills
"""

from alembic import op
import sqlalchemy as sa


revision = "0005_generation_jobs"
down_revision = "0004_outline_context_and_skills"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "generation_jobs" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "generation_jobs",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("project_id", sa.Text(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("job_type", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("stage", sa.Text(), nullable=False, server_default="queued"),
        sa.Column("current", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("message", sa.Text(), nullable=False, server_default=""),
        sa.Column("payload_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("result_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("error", sa.Text()),
        sa.Column("retried_from", sa.Text()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime()),
    )
    op.create_index("ix_generation_jobs_project_id", "generation_jobs", ["project_id"])
    op.create_index("ix_generation_jobs_job_type", "generation_jobs", ["job_type"])
    op.create_index("ix_generation_jobs_status", "generation_jobs", ["status"])
    op.create_index("ix_generation_jobs_retried_from", "generation_jobs", ["retried_from"])


def downgrade() -> None:
    op.drop_table("generation_jobs")
