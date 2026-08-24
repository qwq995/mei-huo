"""add standard constraint review library

Revision ID: 0006_standard_constraints
Revises: 0005_generation_jobs
"""

from alembic import op
import sqlalchemy as sa


revision = "0006_standard_constraints"
down_revision = "0005_generation_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = inspector.get_table_names()
    if "standard_documents" in tables:
        constraint_columns = {column["name"] for column in inspector.get_columns("constraint_atoms")}
        if "review_method" not in constraint_columns:
            op.add_column("constraint_atoms", sa.Column("review_method", sa.Text(), nullable=False, server_default="semantic_review"))
        return
    op.create_table(
        "standard_documents",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("standard_code", sa.Text(), nullable=False, server_default=""),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("disciplines_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("project_types_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("source_path", sa.Text(), nullable=False, server_default=""),
        sa.Column("file_name", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.Text(), nullable=False, unique=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("atom_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("warning_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "constraint_atoms",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("document_id", sa.Text(), sa.ForeignKey("standard_documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("standard_code", sa.Text(), nullable=False, server_default=""),
        sa.Column("standard_name", sa.Text(), nullable=False),
        sa.Column("clause_no", sa.Text(), nullable=False, server_default=""),
        sa.Column("title_path_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("source_text", sa.Text(), nullable=False),
        sa.Column("normalized_requirement", sa.Text(), nullable=False),
        sa.Column("constraint_type", sa.Text(), nullable=False),
        sa.Column("review_method", sa.Text(), nullable=False, server_default="semantic_review"),
        sa.Column("severity", sa.Text(), nullable=False),
        sa.Column("disciplines_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("project_types_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("chapter_scopes_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("keywords_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("applicability_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("exceptions_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("evidence_required_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("ai_fixable", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("repair_instruction", sa.Text(), nullable=False, server_default=""),
        sa.Column("start_line", sa.Integer(), nullable=False),
        sa.Column("end_line", sa.Integer(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0"),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "project_standard_matches",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("project_id", sa.Text(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("document_id", sa.Text(), sa.ForeignKey("standard_documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("match_reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("decision", sa.Text(), nullable=False, server_default="selected"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("project_id", "document_id", name="uq_project_standard_match"),
    )
    op.create_table(
        "compliance_findings",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("project_id", sa.Text(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("node_id", sa.Text(), nullable=False),
        sa.Column("chapter_title", sa.Text(), nullable=False),
        sa.Column("chapter_version_id", sa.Text()),
        sa.Column("atom_id", sa.Text(), sa.ForeignKey("constraint_atoms.id"), nullable=False),
        sa.Column("document_id", sa.Text(), sa.ForeignKey("standard_documents.id"), nullable=False),
        sa.Column("standard_code", sa.Text(), nullable=False, server_default=""),
        sa.Column("standard_name", sa.Text(), nullable=False),
        sa.Column("clause_no", sa.Text(), nullable=False, server_default=""),
        sa.Column("constraint_text", sa.Text(), nullable=False),
        sa.Column("severity", sa.Text(), nullable=False),
        sa.Column("verdict", sa.Text(), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("evidence_quote", sa.Text(), nullable=False, server_default=""),
        sa.Column("ai_fixable", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("suggested_fix", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("resolution_note", sa.Text(), nullable=False, server_default=""),
        sa.Column("resolved_version_id", sa.Text()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("compliance_findings")
    op.drop_table("project_standard_matches")
    op.drop_table("constraint_atoms")
    op.drop_table("standard_documents")
