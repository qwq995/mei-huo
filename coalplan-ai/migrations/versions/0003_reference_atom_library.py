"""add independent reference atom library

Revision ID: 0003_reference_atom_library
Revises: 0002_outline_target_word_count
"""

from alembic import op

from coalplan.infrastructure.database.models import Base


revision = "0003_reference_atom_library"
down_revision = "0002_outline_target_word_count"
branch_labels = None
depends_on = None

TABLES = (
    "reference_documents",
    "reference_chapters",
    "reference_atoms",
    "chapter_atom_usages",
)


def upgrade() -> None:
    bind = op.get_bind()
    for table_name in TABLES:
        Base.metadata.tables[table_name].create(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    for table_name in reversed(TABLES):
        Base.metadata.tables[table_name].drop(bind=bind, checkfirst=True)
