from __future__ import annotations

def ensure_generation_window(pipeline, project_id: str) -> None:
    # The execution window is advisory: it is persisted for the UI so users can
    # see the recommended next action, but it must not prevent a human-led run.
    pipeline.current_execution_window(project_id)
