from __future__ import annotations

from coalplan.infrastructure.database.models import GenerationJobRecord


def ensure_outline_editable(request, project_id: str) -> None:
    """Directory edits are safe before generation, while paused, or after completion."""
    manager = getattr(request.app.state, "job_manager", None)
    if manager is None:
        return
    with manager.session_factory() as session:
        latest = session.query(GenerationJobRecord).filter(
            GenerationJobRecord.project_id == project_id,
            GenerationJobRecord.job_type == "project_generation",
        ).order_by(GenerationJobRecord.created_at.desc()).first()
    if latest is not None and latest.status not in {"paused", "completed"}:
        raise ValueError("全量生成正在执行，请先暂停全量生成或等待其完成后再修改目录。")
