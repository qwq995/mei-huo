"""add outline context and matched skills

Revision ID: 0004_outline_context_and_skills
Revises: 0003_reference_atom_library
"""

from alembic import op
import sqlalchemy as sa


revision = "0004_outline_context_and_skills"
down_revision = "0003_reference_atom_library"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {item["name"] for item in inspector.get_columns("project_outline_nodes")}
    additions = {
        "origin": sa.Column("origin", sa.Text(), nullable=False, server_default="template"),
        "template_anchor_id": sa.Column("template_anchor_id", sa.Text(), nullable=True),
        "source_hints_json": sa.Column("source_hints_json", sa.Text(), nullable=False, server_default="[]"),
        "matched_skill_keys_json": sa.Column("matched_skill_keys_json", sa.Text(), nullable=False, server_default="[]"),
        "chapter_summary_json": sa.Column("chapter_summary_json", sa.Text(), nullable=False, server_default="{}"),
    }
    for name, column in additions.items():
        if name not in columns:
            op.add_column("project_outline_nodes", column)
    indexes = {item["name"] for item in sa.inspect(bind).get_indexes("project_outline_nodes")}
    if "ix_project_outline_nodes_template_anchor_id" not in indexes:
        op.create_index(
            "ix_project_outline_nodes_template_anchor_id",
            "project_outline_nodes",
            ["template_anchor_id"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    indexes = {item["name"] for item in sa.inspect(bind).get_indexes("project_outline_nodes")}
    if "ix_project_outline_nodes_template_anchor_id" in indexes:
        op.drop_index("ix_project_outline_nodes_template_anchor_id", table_name="project_outline_nodes")
    columns = {item["name"] for item in sa.inspect(bind).get_columns("project_outline_nodes")}
    for name in (
        "chapter_summary_json",
        "matched_skill_keys_json",
        "source_hints_json",
        "template_anchor_id",
        "origin",
    ):
        if name in columns:
            op.drop_column("project_outline_nodes", name)
