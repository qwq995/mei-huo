from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from threading import Lock
from typing import Any, Callable
from uuid import uuid4

from coalplan.infrastructure.database.models import GenerationJobRecord
from coalplan.application.reference_import_service import process_reference_markdown
from coalplan.application.compliance_review import run_compliance_review
from coalplan.application.supplement_batch_ai import suggest_supplement_values


ACTIVE_STATUSES = {"queued", "running"}
TERMINAL_STATUSES = {"completed", "partial", "failed", "interrupted", "paused"}
SUPPORTED_JOB_TYPES = {
    "directory_generation",
    "chapter_generation",
    "child_chapter_generation",
    "project_generation",
    "quality_audit",
    "outline_proposal",
    "outline_refine",
    "chapter_plan_proposal",
    "chapter_edit_proposal",
    "reference_import",
    "reference_import_batch",
    "compliance_review",
    "chapter_group_recommendation",
    "chapter_batch_generation",
    "supplement_batch_ai_fill",
}


class JobConflictError(RuntimeError):
    pass


class PauseRequested(RuntimeError):
    pass


def _parallelism(payload: dict[str, Any]) -> int:
    try:
        return max(1, min(int(payload.get("max_parallel_chapters", 1)), 8))
    except (TypeError, ValueError):
        return 1


def _has_selected_version(pipeline, project_id: str, node_id: str) -> bool:
    try:
        return bool(pipeline.workspace_store.get_workspace(project_id, node_id).get("selected_version_id"))
    except (AttributeError, KeyError, TypeError):
        return False


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
        if previous["status"] not in {"failed", "interrupted", "partial", "paused"}:
            raise ValueError("Only failed, interrupted, partial, or paused jobs can be retried.")
        return self.create(project_id, previous["job_type"], previous["payload"], retried_from=job_id)

    def pause(self, project_id: str, job_id: str) -> dict:
        with self._lock, self.session_factory() as session:
            row = session.query(GenerationJobRecord).filter_by(id=job_id, project_id=project_id).one_or_none()
            if row is None:
                raise KeyError(job_id)
            if row.job_type != "project_generation":
                raise ValueError("当前只有全量生成支持暂止。")
            if row.status not in ACTIVE_STATUSES:
                raise ValueError("任务当前不在执行中，无法暂止。")
            row.pause_requested = True
            row.message = "已收到暂止请求，将在当前章节完成后暂停"
            row.updated_at = datetime.now()
            session.commit()
            return _job_dict(row)

    def _run(self, job_id: str) -> None:
        self._update(job_id, status="running", stage="starting", message="正在准备任务")
        try:
            job = self._get_by_id(job_id)
            def progress(stage, current, total, message):
                self._update(job_id, stage=stage, current=current, total=total, message=message)
                if self._pause_requested(job_id):
                    raise PauseRequested()
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
        except PauseRequested:
            latest = self._get_by_id(job_id)
            self._update(
                job_id,
                status="paused",
                stage="paused",
                current=int(latest.get("current") or 0),
                total=int(latest.get("total") or 0),
                message="已暂止，已完成内容和进度已保留，可继续全量生成",
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
            parallelism = _parallelism(payload)
            if parallelism > 1:
                run = self.pipeline.sync_generation_tasks(project_id)
                node_ids = [task.node_id for task in (run.chapter_tasks if run else [])
                            if not payload.get("only_pending", True)
                            or not _has_selected_version(self.pipeline, project_id, task.node_id)]
                return self._run_parallel_chapters(project_id, node_ids, parallelism, progress)
            return _run_dict(self.pipeline.generate_all(
                project_id,
                progress_callback=progress,
                only_pending=bool(payload.get("only_pending", True)),
            ))
        if job_type == "chapter_group_recommendation":
            progress("analysis", 0, 1, "正在分析章节依赖、共享依据和可并行范围")
            result = self.pipeline.recommend_chapter_groups(project_id)
            progress("completed", 1, 1, "章节联合生成建议已完成")
            return result
        if job_type == "chapter_batch_generation":
            node_ids = [str(item) for item in payload.get("node_ids") or [] if str(item)]
            if not node_ids:
                raise ValueError("node_ids is required")
            parallelism = _parallelism(payload)
            if parallelism > 1:
                return self._run_parallel_chapters(project_id, node_ids, parallelism, progress)
            results = []
            failures = []
            for index, node_id in enumerate(node_ids, start=1):
                progress("writing", index - 1, len(node_ids), f"正在更新第 {index}/{len(node_ids)} 个章节")
                try:
                    draft = self.pipeline.generate_one(project_id, node_id, progress_callback=progress)
                    results.append({"node_id": node_id, "draft_id": draft.id, "status": draft.validation_status.value})
                except Exception as exc:
                    failures.append({"node_id": node_id, "error": str(exc)})
            return {"status": "partial" if failures else "completed", "results": results, "failed": failures}
        if job_type == "supplement_batch_ai_fill":
            batch_id = str(payload.get("batch_id") or "")
            if not batch_id:
                raise ValueError("batch_id is required")
            progress("analysis", 0, 1, "正在分析待补信息并生成可审核建议")
            batch = self.pipeline.workspace_store.get_supplement_batch(project_id, batch_id)
            suggestions = suggest_supplement_values(batch=batch, llm=self.pipeline._structured_llm())
            result = self.pipeline.workspace_store.save_supplement_ai_suggestions(project_id, batch_id, suggestions)
            progress("completed", 1, 1, "待补信息建议已生成，等待用户确认")
            return {"batch_id": batch_id, "suggestion_count": len(suggestions), "batch": result}
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
            return self.pipeline.propose_ai_outline(
                project_id, str(payload.get("suggestion") or ""),
                scope_node_id=payload.get("scope_node_id"),
                scope_mode=str(payload.get("scope_mode") or "subtree"),
                preserve_top_level=bool(payload.get("preserve_top_level", True)),
                max_changes=int(payload.get("max_changes") or 20),
                mode=str(payload.get("mode") or "balanced"),
            )
        if job_type == "outline_refine":
            progress("outline", 0, 1, "正在检查目录粒度、依据覆盖和闭环结构")
            return self.pipeline.propose_pre_generation_outline_refine(
                project_id, mode=str(payload.get("mode") or "balanced"), use_local_corpus=True,
                use_human_reference=False, human_reference_markdown=None, project_type=str(payload.get("project_type") or "auto"),
                scope_node_id=payload.get("scope_node_id"), scope_mode=str(payload.get("scope_mode") or "subtree"),
                preserve_top_level=bool(payload.get("preserve_top_level", True)), max_changes=int(payload.get("max_changes") or 20),
            )
        if job_type == "chapter_plan_proposal":
            node_id = str(payload.get("node_id") or "")
            suggestion = str(payload.get("suggestion") or "")
            if not node_id:
                raise ValueError("node_id is required")
            progress("planning", 0, 3, "正在读取本章范围和投标候选依据")
            result = self.pipeline.propose_chapter_generation_plan(project_id, node_id, suggestion)
            progress("proposal", 3, 3, "章节提纲优化建议已生成，等待用户确认")
            return result
        if job_type == "chapter_edit_proposal":
            node_id = str(payload.get("node_id") or "")
            suggestion = str(payload.get("suggestion") or "")
            if not node_id:
                raise ValueError("node_id is required")
            progress("editing", 0, 2, "正在按已确认提纲修改生成正文")
            result = self.pipeline.propose_chapter_edit(project_id, node_id, suggestion)
            progress("proposal", 2, 2, "正文修改建议已生成，等待用户确认")
            return result
        if job_type == "reference_import":
            progress("atomization", 0, int(payload.get("max_batches") or 3), "正在切分章节并提取候选原子")
            return process_reference_markdown(pipeline=self.pipeline, library=self.pipeline.reference_library, payload=payload)
        if job_type == "reference_import_batch":
            files = list(payload.get("files") or [])
            if not files:
                raise ValueError("批量导入至少需要一份 Markdown 文档")
            results = []
            failures = []
            for index, item in enumerate(files, start=1):
                progress("atomization", index - 1, len(files), f"正在切分第 {index}/{len(files)} 份：{item.get('file_name', '未命名')}")
                try:
                    result = process_reference_markdown(pipeline=self.pipeline, library=self.pipeline.reference_library, payload=item)
                    results.append(result)
                except Exception as exc:
                    failures.append({"file_name": item.get("file_name", "未命名"), "error": str(exc)})
            progress("saving", len(files), len(files), "已保存已完成文档，可立即审核候选原子")
            return {"status": "partial" if failures else "success", "results": results, "failed": failures, "document_count": len(results), "atom_count": sum(item.get("atom_count", 0) for item in results)}
        raise ValueError(f"Unsupported job_type: {job_type}")

    def _run_parallel_chapters(self, project_id: str, node_ids: list[str], parallelism: int, progress) -> dict:
        total = len(node_ids)
        if not total:
            return {"status": "completed", "results": [], "failed": []}
        results, failures = [], []
        completed = 0
        progress("writing", 0, total, f"准备并行生成 {total} 个章节（并行数 {parallelism}）")

        def run_one(node_id: str):
            # The worker does not publish inner writing-unit progress, otherwise
            # concurrent chapters would make the global progress jump backwards.
            return self.pipeline.generate_one(project_id, node_id, progress_callback=lambda *_: None)

        with ThreadPoolExecutor(max_workers=parallelism, thread_name_prefix="coalplan-chapter") as executor:
            futures = {executor.submit(run_one, node_id): node_id for node_id in node_ids}
            for future in as_completed(futures):
                node_id = futures[future]
                try:
                    draft = future.result()
                    results.append({"node_id": node_id, "draft_id": draft.id, "status": draft.validation_status.value})
                except Exception as exc:
                    failures.append({"node_id": node_id, "error": str(exc)})
                completed += 1
                progress("writing", completed, total, f"已完成 {completed}/{total} 个章节")
        # Each worker writes its own chapter/version artifacts. Reconcile the
        # single project state once after all workers finish.
        run = self.pipeline.sync_generation_tasks(project_id)
        return {"status": "partial" if failures else "completed", "results": results, "failed": failures,
                "parallelism": parallelism, "run": _run_dict(run) if run else None}

    def _get_by_id(self, job_id: str) -> dict:
        with self.session_factory() as session:
            row = session.query(GenerationJobRecord).filter_by(id=job_id).one()
            return _job_dict(row)

    def _pause_requested(self, job_id: str) -> bool:
        with self.session_factory() as session:
            row = session.query(GenerationJobRecord).filter_by(id=job_id).one()
            return bool(row.pause_requested)

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
        "pause_requested": bool(row.pause_requested),
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
