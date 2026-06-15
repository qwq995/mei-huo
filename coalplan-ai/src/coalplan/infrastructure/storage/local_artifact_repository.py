from __future__ import annotations

from pathlib import Path


class LocalArtifactRepository:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def write_text(self, project_id: str, relative_path: str, content: str) -> str:
        path = self.root / project_id / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return str(path.resolve())

    def read_text(self, path: str) -> str:
        return Path(path).read_text(encoding="utf-8-sig")

