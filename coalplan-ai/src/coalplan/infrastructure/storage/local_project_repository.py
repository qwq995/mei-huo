from __future__ import annotations

import json
from pathlib import Path

from coalplan.domain.generation import Project


class LocalProjectRepository:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def save(self, project: Project) -> Project:
        path = self._path(project.id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(_dump(project), ensure_ascii=False, indent=2), encoding="utf-8")
        return project

    def get(self, project_id: str) -> Project:
        path = self._path(project_id)
        if not path.exists():
            raise KeyError(f"Unknown project_id: {project_id}")
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        return _load_project(data)

    def list(self) -> list[Project]:
        return [_load_project(json.loads(path.read_text(encoding="utf-8-sig"))) for path in sorted(self.root.glob("*/project.json"))]

    def _path(self, project_id: str) -> Path:
        return self.root / project_id / "project.json"


def _dump(model):
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    return model.dict()


def _load_project(data: dict) -> Project:
    if hasattr(Project, "model_validate"):
        return Project.model_validate(data)
    return Project.parse_obj(data)

