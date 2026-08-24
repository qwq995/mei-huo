from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from threading import Lock
from typing import Any, Callable
from uuid import uuid4

from coalplan.infrastructure.database.models import GenerationJobRecord
from coalplan.application.reference_import_service import process_reference_markdown
from coalplan.application.compliance_review import run_compliance_review


ACTIVE_STATUSES = {"queued", "running"}
TERMINAL_STATUSES = {"completed", "partial", "failed", "interrupted"}
SUPPORTED_JOB_TYPES = {
    "directory_generation",
    "chapter_generation",
    "child_chapter_generation",
    "project_generation",
    "quality_audit",
    "outline_proposal",
    "outline_refine",
    "reference_import",
    "compliance_review",
}


class JobConflictError(RuntimeError):
    pass


class GenerationJobManager:
    def __init__(self, session_factory, pipeline, *, standard_constraints=None) -> None:
        self.session_factory = session_factory
        self.pipeline = pipeline
        self.standard_constraints = standard_constraints
        self.executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="coalplan-job")
        self._lock = Lock()
        self._interrupt_stale_jobs()

    def create(self, project_id: str, job_type: str, payload: dict[str, Any] | None = None, *, retried_from: str | None = None) -> dict:
        if job_type not in SUPPORTED_JOB_TYPES:
            raise ValueError(f"Unsupported job_type: {job_type}")
        self.pipeline.projects.get(project_id)
        with self._lock, self.session_factory() as session:
            active = session.query(GenerationJobRecord).filter(
                GenerationJobRecord.project_id == project_id,
                GenerationJobRecord.status.in_(ACTIVE_STATUSES),
            ).order_by(GenerationJobRecord.created_at.desc()).first()
            if active:
                raise JobConflictError(f"Project already has an active job: {active.id}")
            row = GenerationJobRecord(
                id=f"job_{uuid4().hex[:16]}",
                project_id=project_id,
                job_type=job_type,
                status="queued",
                stage="queued",
                message="任务已进入队列",
                payload_json=json.dumps(payload or {}, ensure_ascii=False),
                result_json="{}",
                retried_from=retried_from,
            )
            session.add(row)
            session.commit()
            output = _job_dict(row)
        self.executor.submit(self._run, row.id)
        return output

    def get(self, project_id: str, job_id: str) -> dict:
        with self.session_factory() as session:
            row = session.query(GenerationJobRecord).filter_by(id=job_id, project_id=project_id).one_or_none()
            if row is None:
                raise KeyError(job_id)
            return _job_dict(row)

    def list_recent(self, project_id: str, *, limit: int = 12) -> list[dict]:
        with self.session_factory() as session:
            rows = session.query(GenerationJobRecord).filter_by(project_id=project_id).order_by(
                GenerationJobRecord.created_at.desc()
            ).limit(limit).all()
            return [_job_dict(row) for row in rows]

    def retry(self, project_id: str, job_id: str) -> dict:
        previous = self.get(project_id, job_id)
        if previous["status"] not in {"failed", "interrupted", "partial"}:
            raise ValueError("Only failed, interrupted, or partial jobs can be retried.")
        return self.create(project_id, previous["job_type"], previous["payload"], retried_from=job_id)

    def _run(self, job_id: str) -> None:
        self._update(job_id, status="running", stage="starting", message="正在准备任务")
        try:
            job = self._get_by_id(job_id)
            progress = lambda stage, current, total, message: self._update(
                job_id, stage=stage, current=current, total=total, message=message
            )
            result = self._execute(job["project_id"], job["job_type"], job["payload"], progress)
            status = "partial" if _is_partial_result(result) else "completed"
            latest = self._get_by_id(job_id)
            self._update(
                job_id,
                status=status,
                stage="completed",
                current=max(int(latest.get("total") or 0), int(latest.get("current") or 0), 1),
                message="任务完成" if status == "completed" else "任务完成，但仍有内容需要处理",
                result=result,
                completed=True,
            )
        except Exception as exc:
            self._update(job_id, status="failed", stage="failed", message="任务执行失败，可查看详情后重试", error=str(exc), completed=True)

    def _execute(self, project_id: str, job_type: str, payload: dict, progress: Callable[[str, int, int, str], None]) -> Any:
        if job_type == "directory_generation":
            progress("directory", 0, 1, "正在依据模板和投标资料生成目录")
            project = self.pipeline.prepare_directory(project_id, force=bool(payload.get("force", True)))
            return {"project_id": project.id, "outline_nodes": len(self.pipeline.workspace_store.list_outline_nodes(project_id))}
        if job_type == "chapter_generation":
            node_id = str(payload.get("node_id") or "")
            if not node_id:
                raise ValueError("node_id is required")
            draft = self.pipeline.generate_one(project_id, node_id, progress_callback=progress)
            return {"node_id": node_id, "draft_id": draft.id, "status": draft.validation_status.value, "artifact_path": draft.artifact_path}
        if job_type == "child_chapter_generation":
            node_id = str(payload.get("node_id") or "")
            if not node_id:
                raise ValueError("node_id is required")
            progress("writing", 0, 1, "正在生成所选范围内的待处理章节")
            return self.pipeline.generate_child_chapters(
                project_id,
                node_id,
                recursive=bool(payload.get("recursive", True)),
                only_pending=bool(payload.get("only_pending", True)),
                limit=payload.get("limit", 8),
            )
        if job_type == "project_generation":
            self.pipeline.prepare_run(project_id)
            return _run_dict(self.pipeline.generate_all(project_id, progress_callback=progress))
        if job_type == "quality_audit":
            progress("validation", 0, 1, "正在审查结构、依据覆盖和质量问题")
            return self.pipeline.run_quality_audit(project_id, apply_feedback=bool(payload.get("apply_feedback", True)))
        if job_type == "compliance_review":
            if self.standard_constraints is None:
                raise RuntimeError("规范约束库尚未初始化")
            return run_compliance_review(
                project_id=project_id,
                pipeline=self.pipeline,
                repository=self.standard_constraints,
                progress=progress,
            )
        if job_type == "outline_proposal":
            progress("outline", 0, 1, "正在分析目录调整范围并生成预览方案")
            return self.pipeline.propose_ai_outline(project_id, str(payload.get("suggestion") or ""))
        if job_type == "outline_refine":
            progress("outline", 0, 1, "正在检查目录粒度、依据覆盖和闭环结构")
            return self.pipeline.propose_pre_generation_outline_refine(
                project_id, mode=str(payload.get("mode") or "balanced"), use_local_corpus=True,
                use_human_reference=False, human_reference_markdown=None, project_type=str(payload.get("project_type") or "auto"),
            )
        if job_type == "reference_import":
            progress("atomization", 0, int(payload.get("max_batches") or 3), "正在切分章节并提取候选原子")
            return process_reference_markdown(pipeline=self.pipeline, library=self.pipeline.reference_library, payload=payload)
        raise ValueError(f"Unsupported job_type: {job_type}")

    def _get_by_id(self, job_id: str) -> dict:
        with self.session_factory() as session:
            row = session.query(GenerationJobRecord).filter_by(id=job_id).one()
            return _job_dict(row)

    def _update(self, job_id: str, *, status: str | None = None, stage: str | None = None, current: int | None = None,
                total: int | None = None, message: str | None = None, result: Any | None = None,
                error: str | None = None, completed: bool = False) -> None:
        with self.session_factory() as session:
            row = session.query(GenerationJobRecord).filter_by(id=job_id).one()
            if status is not None:
                row.status = status
            if stage is not None:
                row.stage = stage
            if current is not None:
                row.current = current
            if total is not None:
                row.total = total
            if message is not None:
                row.message = message
            if result is not None:
                row.result_json = json.dumps(result, ensure_ascii=False, default=str)
            if error is not None:
                row.error = error
            row.updated_at = datetime.now()
            if completed:
                row.completed_at = datetime.now()
            session.commit()

    def _interrupt_stale_jobs(self) -> None:
        with self.session_factory() as session:
            rows = session.query(GenerationJobRecord).filter(GenerationJobRecord.status.in_(ACTIVE_STATUSES)).all()
            for row in rows:
                row.status = "interrupted"
                row.stage = "interrupted"
                row.message = "服务曾中断，可从任务中心重新执行"
                row.completed_at = datetime.now()
            session.commit()


def _job_dict(row: GenerationJobRecord) -> dict:
    return {
        "job_id": row.id,
        "project_id": row.project_id,
        "job_type": row.job_type,
        "status": row.status,
        "stage": row.stage,
        "current": row.current,
        "total": row.total,
        "message": row.message,
        "payload": json.loads(row.payload_json or "{}"),
        "result": json.loads(row.result_json or "{}"),
        "error": row.error,
        "retried_from": row.retried_from,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
    }


def _run_dict(run) -> dict:
    tasks = list(run.chapter_tasks)
    return {
        "run_id": run.id,
        "status": run.status.value,
        "task_count": len(tasks),
        "passed_count": sum(task.status.value == "passed" for task in tasks),
        "failed_count": sum(task.status.value == "failed" for task in tasks),
        "final_artifact_path": run.final_artifact_path,
        "logs": list(run.logs),
    }


def _is_partial_result(result: Any) -> bool:
    if not isinstance(result, dict):
        return False
    return bool(result.get("failed")) or result.get("status") in {"partial_failed", "failed"} or result.get("processing_status") == "partial"
