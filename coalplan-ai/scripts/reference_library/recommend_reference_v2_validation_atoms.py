from __future__ import annotations

import argparse
import json
from pathlib import Path

from coalplan.application.hybrid_atom_retrieval import build_atom_search_text, build_query_text
from coalplan.domain.reference_library import AtomRetrievalQuery, ReferenceAtom
from coalplan.infrastructure.vector.qdrant_atom_index import SentenceTransformerEmbedder
from coalplan.settings import get_settings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--validation", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--top-k", type=int, default=12)
    args = parser.parse_args()

    atoms: list[ReferenceAtom] = []
    for path in (args.corpus / "documents").glob("*.json"):
        payload = json.loads(path.read_text(encoding="utf-8"))
        atoms.extend(ReferenceAtom(**item) for item in payload.get("atoms", []))
    curation = json.loads((args.corpus / "curation_report.v2.json").read_text(encoding="utf-8"))
    conflicted = {
        conflict[key]
        for conflict in curation["conflicts"]
        for key in ("left_atom_id", "right_atom_id")
    }
    duplicate_peers: dict[str, set[str]] = {}
    for members in curation["duplicate_groups"].values():
        for atom_id in members:
            duplicate_peers.setdefault(atom_id, set()).update(set(members) - {atom_id})

    validation = json.loads(args.validation.read_text(encoding="utf-8"))
    embedder = SentenceTransformerEmbedder(get_settings().reference_vector_model)
    selections = []
    selected_ids: set[str] = set()
    for scenario in validation["scenarios"]:
        query = AtomRetrievalQuery(**scenario["classified_query"])
        candidates = [
            atom for atom in atoms
            if atom.id not in conflicted
            and not atom.publication_blockers
            and atom.project_name != query.project_name
            and atom.chapter_module == query.chapter_module
            and atom.engineering_system == query.engineering_system
            and atom.process_family == query.process_family
        ]
        texts = [build_query_text(query), *[build_atom_search_text(atom) for atom in candidates]]
        vectors = embedder(texts)
        query_vector = vectors[0]
        ranked = sorted(
            zip(candidates, vectors[1:], strict=True),
            key=lambda item: (_dot(query_vector, item[1]) + item[0].quality_score * 0.05, item[0].quality_score),
            reverse=True,
        )
        chosen = []
        local_ids: set[str] = set()
        for atom, vector in ranked:
            if duplicate_peers.get(atom.id, set()) & (selected_ids | local_ids):
                continue
            chosen.append({
                "atom_id": atom.id,
                "source_project": atom.project_name,
                "title_path": atom.title_path,
                "engineering_object": atom.engineering_object,
                "quality_score": atom.quality_score,
                "semantic_score": round(_dot(query_vector, vector), 6),
            })
            local_ids.add(atom.id)
            if len(chosen) >= args.top_k:
                break
        selected_ids.update(local_ids)
        selections.append({"chapter_title": query.chapter_title, "selected": chosen})

    payload = {
        "schema_version": "v2",
        "selection_method": "AI query classification + controlled tag filter + BGE semantic ranking",
        "selected_count": len(selected_ids),
        "atom_ids": sorted(selected_ids),
        "scenarios": selections,
    }
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "selected_count": payload["selected_count"],
        "scenario_counts": [len(item["selected"]) for item in selections],
        "output": str(args.output),
    }, ensure_ascii=False, indent=2))
    return 0


def _dot(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right, strict=True))


if __name__ == "__main__":
    raise SystemExit(main())
