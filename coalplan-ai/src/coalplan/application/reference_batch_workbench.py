from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from coalplan.application.reference_atomization import build_reference_blocks
from coalplan.domain.documents import stable_id
from coalplan.domain.reference_library import (
    ReferenceAtom,
    ReferenceChapter,
    ReferenceDocument,
    ReferenceDocumentKind,
    ReferenceFactVariable,
    ReferenceReviewStatus,
)


TARGET_PROJECT_TYPES = {
    "水电",
    "水电/大坝",
    "水电/地下洞室",
    "水电/泄洪洞",
    "水电/导流隧洞/边坡",
    "水电/首部枢纽",
    "水电/道路隧洞",
    "水电/道路养护",
    "抽水蓄能",
}


@dataclass
class BatchPreparation:
    run_id: str
    task_dir: Path
    document_count: int
    batch_count: int
    skipped_count: int


def prepare_reference_batches(
    *,
    source_root: Path,
    catalog_path: Path,
    output_dir: Path,
    batch_size: int = 3,
    max_document_chars: int = 120_000,
) -> BatchPreparation:
    """Create model-review packets without calling an external model.

    The only non-semantic preparation here is source preservation: headings,
    blocks and line ranges locate text; the model decides what is valuable.
    """
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    run_id = stable_id("refbatch", f"{catalog_path}:{datetime.now().isoformat()}")
    task_dir = output_dir / run_id / "tasks"
    task_dir.mkdir(parents=True, exist_ok=True)
    entries = [
        item
        for item in catalog.get("documents", [])
        if item.get("atom_candidate")
        and item.get("project_type") in TARGET_PROJECT_TYPES
        and not item.get("exact_duplicate_of")
    ]
    entries.sort(key=lambda item: (item.get("project_type", ""), item.get("project_name", ""), item.get("relative_path", "")))
    tasks: list[dict[str, Any]] = []
    skipped = 0
    for entry in entries:
        path = Path(entry["absolute_path"])
        try:
            raw = path.read_bytes()
            text = raw.decode("utf-8-sig", errors="replace")
        except OSError:
            skipped += 1
            continue
        if len(text) > max_document_chars:
            # Long documents are still included, but are split by blocks below.
            text = text
        blocks = build_reference_blocks(text)
        if not blocks:
            skipped += 1
            continue
        tasks.append({
            "document_id": entry["document_id"],
            "content_hash": entry["content_hash"],
            "source_path": str(path),
            "relative_path": entry.get("relative_path", ""),
            "file_name": entry.get("file_name", path.name),
            "project_name": entry.get("project_name", ""),
            "project_type": entry.get("project_type", ""),
            "instruction": _review_instruction(),
            "blocks": [
                {
                    "block_id": block.block_id,
                    "title_path": block.title_path,
                    "start_line": block.start_line,
                    "end_line": block.end_line,
                    "content": block.content,
                }
                for block in blocks
            ],
        })
    for index in range(0, len(tasks), batch_size):
        batch = tasks[index : index + batch_size]
        (task_dir / f"batch_{index // batch_size + 1:04d}.json").write_text(
            json.dumps({"run_id": run_id, "batch_no": index // batch_size + 1, "documents": batch}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    manifest = {
        "run_id": run_id,
        "source_root": str(source_root.resolve()),
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "policy": "model_only_semantic_review; source_structure_only_for_traceability",
        "document_count": len(tasks),
        "batch_count": (len(tasks) + batch_size - 1) // batch_size,
        "skipped_count": skipped,
        "target_project_types": sorted(TARGET_PROJECT_TYPES),
    }
    (task_dir.parent / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return BatchPreparation(run_id, task_dir, len(tasks), manifest["batch_count"], skipped)


def ingest_reference_decisions(*, task_dir: Path, decision_dir: Path, output_dir: Path) -> dict[str, Any]:
    """Validate model decisions and publish only high-value atoms.

    Decision files contain block ids and labels, never replacement正文. The
    final content is reconstructed from the immutable task packet.
    """
    run_dir = task_dir.parent
    atoms_path = output_dir / "reference_atom_library.jsonl"
    rejected_path = output_dir / "rejected_atoms.jsonl"
    output_dir.mkdir(parents=True, exist_ok=True)
    atoms_path.write_text("", encoding="utf-8")
    rejected_path.write_text("", encoding="utf-8")
    docs: list[dict[str, Any]] = []
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    dedup: dict[str, list[str]] = defaultdict(list)
    missing_batches: list[str] = []
    for task_path in sorted(task_dir.glob("batch_*.json")):
        decision_path = decision_dir / task_path.name
        if not decision_path.exists():
            missing_batches.append(task_path.name)
            continue
        task_payload = json.loads(task_path.read_text(encoding="utf-8"))
        decision_payload = json.loads(decision_path.read_text(encoding="utf-8"))
        by_doc = {item["document_id"]: item for item in task_payload.get("documents", [])}
        for decision_doc in decision_payload.get("documents", decision_payload.get("results", [])):
            doc_id = decision_doc.get("document_id")
            task_doc = by_doc.get(doc_id)
            if not task_doc:
                rejected.append({"document_id": doc_id, "reason": "decision references unknown document"})
                continue
            docs.append({"document_id": doc_id, "file_name": task_doc["file_name"], "status": "completed"})
            blocks = {item["block_id"]: item for item in task_doc["blocks"]}
            for index, candidate in enumerate(decision_doc.get("atoms", []), start=1):
                atom = _validate_candidate(task_doc, blocks, candidate, index)
                if atom is None:
                    rejected.append({"document_id": doc_id, "candidate_index": index, "reason": "invalid source block selection or incomplete atom"})
                    continue
                if atom["reference_value"] != "high":
                    rejected.append({**atom, "reject_reason": candidate.get("reject_reason") or "模型判定参考价值不是 high"})
                    continue
                atom["review_status"] = "published"
                accepted.append(atom)
                group = atom.get("dedup_group") or f"unique:{atom['atom_id']}"
                dedup[group].append(atom["atom_id"])
    accepted = _merge_model_dedup_groups(accepted)
    atoms_path.write_text("\n".join(json.dumps(item, ensure_ascii=False) for item in accepted) + ("\n" if accepted else ""), encoding="utf-8")
    rejected_path.write_text("\n".join(json.dumps(item, ensure_ascii=False) for item in rejected) + ("\n" if rejected else ""), encoding="utf-8")
    summary = {
        "run_id": run_dir.name,
        "document_count": len({item["document_id"] for item in docs}),
        "completed_document_count": len(docs),
        "published_atom_count": len(accepted),
        "rejected_count": len(rejected),
        "missing_batches": missing_batches,
        "dedup_groups": {key: value for key, value in dedup.items()},
        "coverage_by_process": dict(Counter(item.get("process", "") for item in accepted if item.get("process"))),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }
    (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_document_csv(output_dir / "document_processing.csv", docs, missing_batches)
    (output_dir / "summary.md").write_text(_render_summary(summary), encoding="utf-8")
    (output_dir / "dedup_groups.json").write_text(json.dumps(summary["dedup_groups"], ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def sync_reference_library_to_database(*, task_dir: Path, library_path: Path, repository) -> dict[str, int]:
    """Publish an already validated batch artifact to the management database.

    The batch files remain the auditable source artifact. This operation only
    mirrors their documents, chapter ranges, and published atoms into the same
    repository used by the API and management console, and is safe to rerun.
    """
    atoms_by_document: dict[str, list[ReferenceAtom]] = defaultdict(list)
    if library_path.exists():
        for line in library_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            item = json.loads(line)
            source_lines = item.get("source_lines") or {}
            atoms_by_document[item["document_id"]].append(
                ReferenceAtom(
                    id=item["atom_id"],
                    document_id=item["document_id"],
                    project_name=item.get("project_name", ""),
                    project_type=item.get("project_type", ""),
                    title_path=item.get("title_path", []),
                    content=item.get("content", ""),
                    source_block_ids=item.get("source_block_ids", []),
                    start_line=int(source_lines.get("start", 0)),
                    end_line=int(source_lines.get("end", 0)),
                    engineering_object=item.get("engineering_object", ""),
                    specialty=item.get("specialty", ""),
                    work_item=item.get("work_item", ""),
                    process=item.get("process", ""),
                    process_stage=item.get("process_stage", ""),
                    chapter_type=item.get("chapter_type", ""),
                    content_functions=item.get("content_functions", []),
                    applicability=item.get("applicability", []),
                    prohibited_scenarios=item.get("prohibited_scenarios", []),
                    fact_variables=[ReferenceFactVariable(**value) for value in item.get("fact_variables", [])],
                    quality_score=float(item.get("quality_score", 0) or 0),
                    confidence=float(item.get("confidence", 0) or 0),
                    reference_value=item.get("reference_value", "high"),
                    value_reason=item.get("value_reason", ""),
                    reuse_scope=item.get("reuse_scope", []),
                    migration_warning=item.get("migration_warning", []),
                    dedup_group=item.get("dedup_group", ""),
                    status=ReferenceReviewStatus.published,
                    version=1,
                )
            )

    document_count = 0
    atom_count = 0
    for task_path in sorted(task_dir.glob("batch_*.json")):
        payload = json.loads(task_path.read_text(encoding="utf-8"))
        for item in payload.get("documents", []):
            kind = (
                ReferenceDocumentKind.construction_organization
                if "施工组织设计" in item.get("file_name", "")
                else ReferenceDocumentKind.special_plan
            )
            document = ReferenceDocument(
                id=item["document_id"],
                content_hash=item["content_hash"],
                source_path=item["source_path"],
                file_name=item["file_name"],
                project_name=item.get("project_name", ""),
                project_type=item.get("project_type", ""),
                document_kind=kind,
                status=ReferenceReviewStatus.imported,
            )
            repository.save_document(document)
            ranges: dict[tuple[str, ...], tuple[int, int]] = {}
            for block in item.get("blocks", []):
                path = tuple(block.get("title_path", []))
                if not path:
                    continue
                start, end = ranges.get(path, (block["start_line"], block["end_line"]))
                ranges[path] = (min(start, block["start_line"]), max(end, block["end_line"]))
            chapters = [
                ReferenceChapter(
                    id=stable_id("refchapter", f"{item['document_id']}:{' > '.join(path)}"),
                    document_id=item["document_id"],
                    title_path=list(path),
                    start_line=line_range[0],
                    end_line=line_range[1],
                    sort_order=index,
                )
                for index, (path, line_range) in enumerate(ranges.items(), start=1)
            ]
            repository.replace_document_content(
                item["document_id"], chapters=chapters, atoms=atoms_by_document.get(item["document_id"], [])
            )
            document_count += 1
            atom_count += len(atoms_by_document.get(item["document_id"], []))
    return {"document_count": document_count, "published_atom_count": atom_count}


def _validate_candidate(task_doc: dict[str, Any], blocks: dict[str, dict[str, Any]], candidate: dict[str, Any], index: int) -> dict[str, Any] | None:
    block_ids = [str(value) for value in candidate.get("block_ids", [])]
    selected = [blocks[item] for item in block_ids if item in blocks]
    if not selected or len(selected) != len(block_ids):
        return None
    content = "\n\n".join(item["content"] for item in selected).strip()
    if len(content) < 80:
        return None
    if candidate.get("content") and candidate["content"].strip() != content:
        return None
    value = str(candidate.get("reference_value", "low")).strip().lower()
    if value not in {"high", "medium", "low"}:
        value = "low"
    source_hash = hashlib.sha256((task_doc["document_id"] + ":" + ":".join(block_ids)).encode()).hexdigest()[:12]
    return {
        "atom_id": stable_id("atom", f"{task_doc['document_id']}:{':'.join(block_ids)}"),
        "source_document": task_doc["source_path"],
        "document_id": task_doc["document_id"],
        "project_name": task_doc["project_name"],
        "project_type": task_doc["project_type"],
        "title_path": candidate.get("title_path") or selected[0].get("title_path", []),
        "source_lines": {"start": min(item["start_line"] for item in selected), "end": max(item["end_line"] for item in selected)},
        "content": content,
        "source_block_ids": block_ids,
        "engineering_object": str(candidate.get("engineering_object", "")).strip(),
        "specialty": str(candidate.get("specialty", "")).strip(),
        "work_item": str(candidate.get("work_item", "")).strip(),
        "process": str(candidate.get("process", "")).strip(),
        "process_stage": str(candidate.get("process_stage", "")).strip(),
        "chapter_type": str(candidate.get("chapter_type", "")).strip(),
        "content_functions": candidate.get("content_functions", []),
        "applicability": candidate.get("applicability", []),
        "prohibited_scenarios": candidate.get("prohibited_scenarios", []),
        "fact_variables": candidate.get("fact_variables", []),
        "quality_score": float(candidate.get("quality_score", 0) or 0),
        "confidence": float(candidate.get("confidence", 0) or 0),
        "reference_value": value,
        "value_reason": str(candidate.get("value_reason", "")).strip(),
        "reuse_scope": candidate.get("reuse_scope", []),
        "migration_warning": candidate.get("migration_warning", []),
        "dedup_group": str(candidate.get("dedup_group", "")).strip(),
        "source_selection_hash": source_hash,
        "candidate_index": index,
    }


def _merge_model_dedup_groups(atoms: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep one representative per model-declared semantic duplicate group."""
    merged: dict[str, dict[str, Any]] = {}
    for atom in atoms:
        key = atom.get("dedup_group") or f"unique:{atom['atom_id']}"
        current = merged.get(key)
        if current is None:
            atom["duplicate_sources"] = []
            merged[key] = atom
            continue
        current.setdefault("duplicate_sources", []).append({
            "source_document": atom["source_document"],
            "source_lines": atom["source_lines"],
            "atom_id": atom["atom_id"],
        })
    return list(merged.values())


def _review_instruction() -> str:
    return """仅使用模型语义判断完成审查。只能返回已有 block_id，不能改写 content。只保留具有具体施工动作、工序/控制逻辑、至少一个质量安全进度或验收闭环、跨项目仍可借鉴的原子。项目名称、地名、桩号、工程量、日期、参数、设备型号和规范版本全部放入 fact_variables，并标记不得直接迁移。空泛口号、目录、审批意见、纯背景、纯规范罗列和仅项目事实段落不要输出。reference_value 只能是 high/medium/low；只有 high 会进入发布库。"""


def _write_document_csv(path: Path, docs: list[dict[str, Any]], missing: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["document_id", "file_name", "status"])
        writer.writeheader()
        writer.writerows(docs)
        for item in missing:
            writer.writerow({"document_id": "", "file_name": item, "status": "pending_or_failed"})


def _render_summary(summary: dict[str, Any]) -> str:
    lines = [
        "# 水电施组原子库批处理结果", "", f"- 处理文档：{summary['document_count']}",
        f"- 已完成文档：{summary['completed_document_count']}", f"- 发布原子：{summary['published_atom_count']}",
        f"- 淘汰记录：{summary['rejected_count']}", f"- 待续跑批次：{len(summary['missing_batches'])}", "",
        "## 工艺覆盖", "",
    ]
    lines.extend(f"- {key}: {value}" for key, value in summary["coverage_by_process"].items())
    lines.extend(["", "## 处理说明", "", "原子正文均由任务包中的原文 block 回拼；模型只负责语义切分、价值判断、标签和去重组。只有 reference_value=high 的原子进入发布库。"])
    return "\n".join(lines) + "\n"
