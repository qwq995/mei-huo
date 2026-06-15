from __future__ import annotations

from coalplan.domain.generation import Project
from coalplan.ports.template_loader import TemplateLoader


def load_template_tree(project: Project, *, template_id: str, loader: TemplateLoader) -> Project:
    project.template_id = template_id
    project.template_tree = loader.load(template_id)
    return project

