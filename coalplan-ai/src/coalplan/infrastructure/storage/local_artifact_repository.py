from __future__ import annotations

from pathlib import Path
from uuid import uuid4


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

    def write_bytes(self, project_id: str, relative_path: str, content: bytes) -> str:
        path = self.root / project_id / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return str(path.resolve())

    def unique_attachment_path(self, node_id: str, file_name: str) -> str:
        safe_name = "".join(ch if ch.isalnum() or ch in ".-_" else "_" for ch in file_name).strip("_") or "attachment"
        return f"attachments/{node_id}/{uuid4().hex[:12]}_{safe_name}"
