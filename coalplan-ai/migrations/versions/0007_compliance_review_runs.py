"""persist compliance review runs and matched constraints

Revision ID: 0007_compliance_review_runs
Revises: 0006_standard_constraints
"""

from alembic import op
import sqlalchemy as sa


revision = "0007_compliance_review_runs"
down_revision = "0006_standard_constraints"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = inspector.get_table_names()
    if "compliance_findings" in tables:
        columns = {column["name"] for column in inspector.get_columns("compliance_findings")}
        if "run_id" not in columns:
            op.add_column("compliance_findings", sa.Column("run_id", sa.Text(), nullable=False, server_default=""))
            op.create_index("ix_compliance_findings_run_id", "compliance_findings", ["run_id"])
    if "compliance_review_runs" not in tables:
        op.create_table(
            "compliance_review_runs",
            sa.Column("id", sa.Text(), primary_key=True),
            sa.Column("project_id", sa.Text(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
            sa.Column("status", sa.Text(), nullable=False),
            sa.Column("chapter_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("matched_document_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("candidate_constraint_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("finding_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("warnings_json", sa.Text(), nullable=False, server_default="[]"),
            sa.Column("summary_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("completed_at", sa.DateTime()),
        )
        op.create_index("ix_compliance_review_runs_project_id", "compliance_review_runs", ["project_id"])
        op.create_index("ix_compliance_review_runs_status", "compliance_review_runs", ["status"])
    if "compliance_constraint_matches" not in tables:
        op.create_table(
            "compliance_constraint_matches",
            sa.Column("id", sa.Text(), primary_key=True),
            sa.Column("run_id", sa.Text(), sa.ForeignKey("compliance_review_runs.id", ondelete="CASCADE"), nullable=False),
            sa.Column("project_id", sa.Text(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
            sa.Column("node_id", sa.Text(), nullable=False),
            sa.Column("chapter_version_id", sa.Text(), nullable=False),
            sa.Column("atom_id", sa.Text(), sa.ForeignKey("constraint_atoms.id"), nullable=False),
            sa.Column("document_id", sa.Text(), sa.ForeignKey("standard_documents.id"), nullable=False),
            sa.Column("score", sa.Float(), nullable=False, server_default="0"),
            sa.Column("match_reason", sa.Text(), nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        for name, column in (
            ("ix_compliance_constraint_matches_run_id", "run_id"),
            ("ix_compliance_constraint_matches_project_id", "project_id"),
            ("ix_compliance_constraint_matches_node_id", "node_id"),
            ("ix_compliance_constraint_matches_chapter_version_id", "chapter_version_id"),
            ("ix_compliance_constraint_matches_atom_id", "atom_id"),
            ("ix_compliance_constraint_matches_document_id", "document_id"),
        ):
            op.create_index(name, "compliance_constraint_matches", [column])


def downgrade() -> None:
    op.drop_table("compliance_constraint_matches")
    op.drop_table("compliance_review_runs")
    op.drop_index("ix_compliance_findings_run_id", table_name="compliance_findings")
    op.drop_column("compliance_findings", "run_id")
