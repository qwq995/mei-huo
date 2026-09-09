from __future__ import annotations

import hashlib
import json
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from coalplan.application.reference_atomization_v2 import (
    ATOM_MATERIALIZATION_VERSION,
    ATOMIZATION_PROMPT_VERSION,
    atomize_reference_markdown_v2,
    build_semantic_segments,
)
from coalplan.application.reference_atom_curation import curate_reference_atoms
from coalplan.application.reference_section_routing import route_reference_sections
from coalplan.application.serialization import dump_model
from coalplan.domain.documents import stable_id
from coalplan.domain.reference_library import ReferenceAtom, ReferenceDocument, ReferenceDocumentKind
from coalplan.ports.llm import StructuredLLMClient


@dataclass(frozen=True)
class CorpusPreparation:
    manifest_path: Path
    document_count: int
    segment_count: int
    character_count: int


def route_v2_corpus(
    *,
    manifest_path: Path,
    output_dir: Path,
    llm: StructuredLLMClient,
    max_documents: int | None = None,
    concurrency: int = 4,
    batch_concurrency: int = 1,
    force: bool = False,
) -> dict:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    items = manifest["documents"][:max_documents]
    route_dir = output_dir / "routes"
    route_dir.mkdir(parents=True, exist_ok=True)

    def process(item: dict) -> dict:
        path = route_dir / f"{item['document_id']}.json"
        previous = None
        if path.exists():
            previous = json.loads(path.read_text(encoding="utf-8"))
        if path.exists() and not force:
            if previous.get("status") == "completed":
                return previous
        document = ReferenceDocument(
            id=item["document_id"], content_hash=item["content_hash"], source_path=item["source_path"],
            file_name=item["file_name"], project_name=item["project_name"], project_type=item["project_type"],
            document_kind=ReferenceDocumentKind.construction_organization,
        )
        try:
            markdown = Path(item["source_path"]).read_text(encoding="utf-8-sig", errors="replace")
            segments = build_semantic_segments(markdown)
            routing = route_reference_sections(
                document=document,
                segments=segments,
                llm=llm,
                concurrency=batch_concurrency,
                checkpoint_dir=output_dir / "route-checkpoints" / document.id,
            )
            selected_ids = [segment.block_id for segment in routing.selected_segments]
            selected_set = set(selected_ids)
            route_counts = {
                route_name: sum(route.route == route_name for route in routing.routes)
                for route_name in ("atom_source", "chapter_sample", "project_fact", "exclude")
            }
            atom_source_ratio = route_counts["atom_source"] / max(1, len(routing.routes))
            quality_warnings = []
            if atom_source_ratio > 0.65:
                quality_warnings.append("技术原子来源路径超过 65%，原子化后应重点抽查章节框架误收")
            if atom_source_ratio < 0.05:
                quality_warnings.append("技术原子来源路径不足 5%，应抽查是否漏掉有效施工方法")
            payload = {
                "status": "completed" if not routing.failed_batches else "partial",
                "document_id": document.id,
                "project_type": routing.project_type,
                "routes": [route.__dict__ for route in routing.routes],
                "selected_segment_ids": selected_ids,
                "selected_segment_count": len(selected_ids),
                "selected_character_count": sum(len(segment.content) for segment in segments if segment.block_id in selected_set),
                "total_segment_count": len(segments),
                "llm_call_count": routing.llm_call_count,
                "failed_batches": routing.failed_batches,
                "route_counts": route_counts,
                "atom_source_path_ratio": round(atom_source_ratio, 4),
                "quality_warnings": quality_warnings,
                "generated_at": datetime.now().isoformat(timespec="seconds"),
            }
        except Exception as exc:
            payload = {"status": "failed", "document_id": item["document_id"], "error": str(exc)[:1000]}

        # A failed or partial forced retry must never destroy a previously
        # complete routing decision. Keep the attempt for diagnosis and let
        # downstream atomization continue from the last known-good result.
        if previous and previous.get("status") == "completed" and payload.get("status") != "completed":
            attempt_path = route_dir / f"{item['document_id']}.attempt-{datetime.now().strftime('%Y%m%d%H%M%S')}.json"
            _atomic_write_json(attempt_path, payload)
            retained = dict(previous)
            retained["retry_warning"] = {
                "attempt_status": payload.get("status"),
                "error": payload.get("error"),
                "failed_batches": payload.get("failed_batches", []),
                "attempt_path": str(attempt_path),
            }
            return retained
        _atomic_write_json(path, payload)
        return payload

    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=max(1, min(concurrency, 8))) as executor:
        futures = [executor.submit(process, item) for item in items]
        for future in as_completed(futures):
            results.append(future.result())
    completed = [item for item in results if item.get("status") == "completed"]
    partial = [item for item in results if item.get("status") == "partial"]
    summary = {
        "document_count": len(items),
        "completed": len(completed),
        "partial": len(partial),
        "failed": len(results) - len(completed) - len(partial),
        "selected_segment_count": sum(item.get("selected_segment_count", 0) for item in completed),
        "selected_character_count": sum(item.get("selected_character_count", 0) for item in completed),
        "total_segment_count": sum(item.get("total_segment_count", 0) for item in completed),
        "llm_call_count": sum(item.get("llm_call_count", 0) for item in completed),
        "route_dir": str(route_dir),
    }
    _atomic_write_json(output_dir / "routing_summary.v2.json", summary)
    return summary


def prepare_v2_corpus(source_root: Path, output_dir: Path) -> CorpusPreparation:
    source_root = source_root.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    documents = []
    total_segments = 0
    total_chars = 0
    for path in sorted(source_root.rglob("*.md")):
        raw = path.read_bytes()
        text = raw.decode("utf-8-sig", errors="replace")
        digest = hashlib.sha256(raw).hexdigest()
        segments = build_semantic_segments(text)
        total_segments += len(segments)
        total_chars += len(text)
        documents.append({
            "document_id": stable_id("refdoc", digest),
            "content_hash": digest,
            "source_path": str(path),
            "relative_path": str(path.relative_to(source_root)),
            "file_name": path.name,
            "project_name": _project_name(path, source_root),
            "project_type": "待 AI 识别",
            "document_kind": ReferenceDocumentKind.construction_organization.value,
            "character_count": len(text),
            "segment_count": len(segments),
            "status": "prepared",
        })
    manifest = {
        "schema_version": "v2",
        "source_root": str(source_root),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "document_count": len(documents),
        "segment_count": total_segments,
        "character_count": total_chars,
        "documents": documents,
    }
    manifest_path = output_dir / "corpus_manifest.v2.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return CorpusPreparation(manifest_path, len(documents), total_segments, total_chars)


def process_v2_corpus(
    *,
    manifest_path: Path,
    output_dir: Path,
    llm: StructuredLLMClient,
    repository=None,
    start_document: int = 0,
    max_documents: int | None = None,
    max_batches_per_document: int | None = None,
    concurrency: int = 1,
) -> dict:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    result_dir = output_dir / "documents"
    result_dir.mkdir(parents=True, exist_ok=True)
    completed = failed = excluded_documents = atom_count = pending_count = 0
    selected_documents = manifest["documents"][max(0, start_document):]
    if max_documents is not None:
        selected_documents = selected_documents[:max_documents]
    for item in selected_documents:
        result_path = result_dir / f"{item['document_id']}.json"
        if result_path.exists():
            existing = json.loads(result_path.read_text(encoding="utf-8"))
            if (
                existing.get("status") == "completed"
                and existing.get("atomization_prompt_version") == ATOMIZATION_PROMPT_VERSION
                and existing.get("materialization_version") == ATOM_MATERIALIZATION_VERSION
                and bool(existing.get("atoms"))
            ):
                completed += 1
                atom_count += len(existing.get("atoms", []))
                pending_count += sum(atom.get("status") == "pending_publish" for atom in existing.get("atoms", []))
                continue
        document = ReferenceDocument(
            id=item["document_id"], content_hash=item["content_hash"], source_path=item["source_path"],
            file_name=item["file_name"], project_name=item["project_name"], project_type=item["project_type"],
            document_kind=ReferenceDocumentKind.construction_organization,
        )
        try:
            markdown = Path(item["source_path"]).read_text(encoding="utf-8-sig", errors="replace")
            segments = build_semantic_segments(markdown)
            route_path = output_dir / "routes" / f"{document.id}.json"
            if route_path.exists():
                route_payload = json.loads(route_path.read_text(encoding="utf-8"))
            else:
                route_payload = {}
            if route_payload.get("status") == "completed":
                selected_ids = set(route_payload.get("selected_segment_ids", []))
                selected_segments = [segment for segment in segments if segment.block_id in selected_ids]
                document.project_type = route_payload.get("project_type") or document.project_type
                section_routes = route_payload.get("routes", [])
                routing_call_count = 0
            else:
                routing = route_reference_sections(document=document, segments=segments, llm=llm)
                selected_segments = routing.selected_segments
                document.project_type = routing.project_type
                section_routes = [route.__dict__ for route in routing.routes]
                routing_call_count = routing.llm_call_count
            if not selected_segments:
                _atomic_write_json(result_path, {
                    "status": "excluded_no_technical_content",
                    "atomization_prompt_version": ATOMIZATION_PROMPT_VERSION,
                    "materialization_version": ATOM_MATERIALIZATION_VERSION,
                    "document": dump_model(document),
                    "atoms": [],
                    "section_routes": section_routes,
                    "selected_segment_count": 0,
                    "excluded_segments": [],
                    "failed_batches": [],
                    "processed_batch_count": 0,
                    "total_batch_count": 0,
                    "llm_call_count": routing_call_count,
                })
                excluded_documents += 1
                continue
            result = atomize_reference_markdown_v2(
                document=document, markdown=markdown, llm=llm, max_batches=max_batches_per_document,
                selected_segments=selected_segments,
                concurrency=concurrency,
                checkpoint_dir=output_dir / "atom-checkpoints" / document.id,
            )
            limited = result.processed_batch_count < result.total_batch_count
            payload = {
                "status": "completed" if not result.failed_batches and not limited else "partial",
                "atomization_prompt_version": ATOMIZATION_PROMPT_VERSION,
                "materialization_version": ATOM_MATERIALIZATION_VERSION,
                "document": dump_model(document),
                "atoms": [dump_model(atom) for atom in result.atoms],
                "section_routes": section_routes,
                "selected_segment_count": len(selected_segments),
                "excluded_segments": result.excluded_segments,
                "failed_batches": result.failed_batches,
                "processed_batch_count": result.processed_batch_count,
                "total_batch_count": result.total_batch_count,
                "llm_call_count": routing_call_count + result.llm_call_count,
            }
            _atomic_write_json(result_path, payload)
            if repository is not None:
                repository.save_document(document)
                repository.replace_document_content(document.id, chapters=[], atoms=result.atoms)
            completed += payload["status"] == "completed"
            failed += payload["status"] != "completed"
            atom_count += len(result.atoms)
            pending_count += sum(atom.status.value == "pending_publish" for atom in result.atoms)
        except Exception as exc:
            failed += 1
            _atomic_write_json(result_path, {"status": "failed", "error": str(exc)})
    summary = {
        "document_count": len(selected_documents),
        "start_document": max(0, start_document),
        "completed": completed,
        "failed_or_partial": failed,
        "excluded_no_technical_content": excluded_documents,
        "atom_count": atom_count,
        "pending_publish_count": pending_count,
        "result_dir": str(result_dir),
    }
    _atomic_write_json(output_dir / "run_summary.v2.json", summary)
    return summary


def curate_v2_corpus(output_dir: Path) -> dict:
    result_dir = output_dir / "documents"
    documents: dict[str, dict] = {}
    atoms: list[ReferenceAtom] = []
    for path in sorted(result_dir.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if (
            payload.get("status") not in {"completed", "partial"}
            or payload.get("atomization_prompt_version") != ATOMIZATION_PROMPT_VERSION
            or payload.get("materialization_version") != ATOM_MATERIALIZATION_VERSION
            or not payload.get("atoms")
        ):
            continue
        documents[str(path)] = payload
        atoms.extend(ReferenceAtom(**item) for item in payload.get("atoms", []))
    curated = curate_reference_atoms(atoms)
    atom_by_id = {atom.id: atom for atom in curated.atoms}
    for path_text, payload in documents.items():
        payload["atoms"] = [dump_model(atom_by_id[item["id"]]) for item in payload.get("atoms", []) if item["id"] in atom_by_id]
        _atomic_write_json(Path(path_text), payload)
    report = {
        "atom_count": len(curated.atoms),
        "duplicate_group_count": len(curated.duplicate_groups),
        "duplicate_groups": curated.duplicate_groups,
        "conflict_count": len(curated.conflicts),
        "conflicts": [item.__dict__ for item in curated.conflicts],
    }
    _atomic_write_json(output_dir / "curation_report.v2.json", report)
    catalog = _build_atom_catalog(curated.atoms, documents)
    _atomic_write_json(output_dir / "atom_catalog.v2.json", catalog)
    (output_dir / "atom_catalog.v2.md").write_text(_render_atom_catalog(catalog), encoding="utf-8")
    return report


def sync_v2_corpus(output_dir: Path, repository) -> dict:
    """Persist completed and partial V2 results without publishing candidates."""
    synced_documents = 0
    synced_atoms = 0
    skipped: list[dict[str, str]] = []
    for path in sorted((output_dir / "documents").glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("status") not in {"completed", "partial"}:
            skipped.append({"path": str(path), "reason": f"status={payload.get('status')}"})
            continue
        if payload.get("atomization_prompt_version") != ATOMIZATION_PROMPT_VERSION:
            skipped.append({"path": str(path), "reason": "stale atomization prompt version"})
            continue
        if payload.get("materialization_version") != ATOM_MATERIALIZATION_VERSION:
            skipped.append({"path": str(path), "reason": "stale materialization version"})
            continue
        if not payload.get("atoms"):
            skipped.append({"path": str(path), "reason": "no reusable technical atoms"})
            try:
                repository.delete_document(payload["document"]["id"])
            except KeyError:
                pass
            continue
        try:
            document = ReferenceDocument(**payload["document"])
            atoms = [ReferenceAtom(**item) for item in payload.get("atoms", [])]
            repository.save_document(document, refresh_search_indexes=False)
            repository.replace_document_content(
                document.id,
                chapters=[],
                atoms=atoms,
                refresh_search_indexes=False,
            )
        except Exception as exc:
            skipped.append({"path": str(path), "reason": str(exc)[:300]})
            continue
        synced_documents += 1
        synced_atoms += len(atoms)
    repository.refresh_search_indexes()
    summary = {
        "synced_documents": synced_documents,
        "synced_atoms": synced_atoms,
        "skipped": skipped,
        "published_atoms": 0,
        "note": "同步不会自动发布；仅用户批量确认并通过 V2 门禁的原子进入生成检索。",
    }
    _atomic_write_json(output_dir / "database_sync_summary.v2.json", summary)
    return summary


def _project_name(path: Path, source_root: Path) -> str:
    relative = path.relative_to(source_root)
    if len(relative.parts) > 1:
        return relative.parts[0]
    return path.stem


def _atomic_write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _build_atom_catalog(atoms: list[ReferenceAtom], documents: dict[str, dict]) -> dict:
    def counts(field: str) -> dict[str, int]:
        return dict(sorted(Counter(str(getattr(atom, field) or "未标注") for atom in atoms).items()))

    status_counts = Counter(atom.status.value for atom in atoms)
    document_counts = Counter(atom.document_id for atom in atoms)
    eligible = [atom for atom in atoms if not atom.publication_blockers]
    return {
        "schema_version": "v2",
        "atomization_prompt_version": ATOMIZATION_PROMPT_VERSION,
        "materialization_version": ATOM_MATERIALIZATION_VERSION,
        "document_result_count": len(documents),
        "atom_count": len(atoms),
        "publication_gate_passed": len(eligible),
        "status_counts": dict(sorted(status_counts.items())),
        "chapter_modules": counts("chapter_module"),
        "engineering_systems": counts("engineering_system"),
        "process_families": counts("process_family"),
        "atom_types": counts("atom_type"),
        "parameter_slot_count": sum(len(atom.parameter_slots) for atom in atoms),
        "average_quality_score": round(sum(atom.quality_score for atom in atoms) / max(1, len(atoms)), 4),
        "documents": [
            {"document_id": document_id, "atom_count": count}
            for document_id, count in sorted(document_counts.items(), key=lambda item: (-item[1], item[0]))
        ],
    }


def _render_atom_catalog(catalog: dict) -> str:
    lines = [
        "# 优秀施组 V2 原子目录",
        "",
        f"- 文档结果：{catalog['document_result_count']}",
        f"- 原子总数：{catalog['atom_count']}",
        f"- 发布门禁通过：{catalog['publication_gate_passed']}",
        f"- 参数槽：{catalog['parameter_slot_count']}",
        f"- 平均质量分：{catalog['average_quality_score']}",
    ]
    for title, key in (
        ("文档模块", "chapter_modules"),
        ("工程系统", "engineering_systems"),
        ("工艺族", "process_families"),
        ("原子类型", "atom_types"),
    ):
        lines.extend(["", f"## {title}", "", "| 标识 | 数量 |", "|---|---:|"])
        lines.extend(f"| {name} | {count} |" for name, count in catalog[key].items())
    return "\n".join(lines) + "\n"
