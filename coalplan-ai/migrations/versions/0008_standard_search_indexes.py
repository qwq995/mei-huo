"""add local FTS indexes for standards and constraint retrieval

Revision ID: 0008_standard_search_indexes
Revises: 0007_compliance_review_runs
"""

from alembic import op
import sqlalchemy as sa


revision = "0008_standard_search_indexes"
down_revision = "0007_compliance_review_runs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        return
    inspector = sa.inspect(bind)
    if not {"standard_documents", "constraint_atoms"}.issubset(set(inspector.get_table_names())):
        return
    op.execute(
        "CREATE VIRTUAL TABLE IF NOT EXISTS standard_document_search "
        "USING fts5(document_id UNINDEXED, search_text)"
    )
    op.execute(
        "CREATE VIRTUAL TABLE IF NOT EXISTS constraint_atom_search "
        "USING fts5(atom_id UNINDEXED, document_id UNINDEXED, search_text)"
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        return
    op.execute("DROP TABLE IF EXISTS constraint_atom_search")
    op.execute("DROP TABLE IF EXISTS standard_document_search")
