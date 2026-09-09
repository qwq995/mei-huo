from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from coalplan.application.serialization import dump_model
from coalplan.infrastructure.llm.codex_cli import CodexCliStructuredLLMClient
from coalplan.infrastructure.vector.qdrant_atom_index import QdrantAtomVectorIndex, SentenceTransformerEmbedder
from coalplan.main import build_pipeline
from coalplan.settings import get_settings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--node-id", required=True)
    parser.add_argument("--model", default="gpt-5.6-luna")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=int, default=1200)
    args = parser.parse_args()

    settings = get_settings().model_copy(update={
        "llm_provider": "fake",
        "structured_llm_provider": None,
        "reference_vector_enabled": False,
    })
    pipeline = build_pipeline(settings)
    trace_dir = args.output.parent / (
        "chapter-generation-traces-" + datetime.now().strftime("%Y%m%dT%H%M%S")
    )
    client = CodexCliStructuredLLMClient(
        model=args.model,
        workdir=Path.cwd(),
        trace_dir=trace_dir,
        timeout=args.timeout,
    )
    pipeline.llm = client
    pipeline.structured_llm = client

    storage = settings.storage_dir.resolve()
    vector_path = settings.reference_vector_path
    if not vector_path.is_absolute():
        vector_path = storage / vector_path
    embedder = SentenceTransformerEmbedder(settings.reference_vector_model)
    vector_index = QdrantAtomVectorIndex(
        embed=embedder,
        dimension=embedder.dimension,
        url=settings.reference_vector_url,
        path=vector_path,
    )
    pipeline.reference_vector_index = vector_index
    progress: list[dict] = []

    def on_progress(stage: str, current: int, total: int, message: str) -> None:
        item = {"stage": stage, "current": current, "total": total, "message": message}
        progress.append(item)
        print(json.dumps(item, ensure_ascii=False), flush=True)

    existing_usage_ids = {
        str(item.get("id") or "")
        for item in pipeline.reference_library.list_usage(args.project_id, args.node_id)
    }
    try:
        draft = pipeline.generate_one(
            args.project_id,
            args.node_id,
            revision_context=(
                "本次为 V2 优秀施组原子库联调验证。项目事实仍只允许来自当前投标证据；"
                "参考原子仅用于补充钻爆施工工序、控制点、检查闭环和专业表达，"
                "不得迁移原子中的工程名称、桩号、数量或历史参数。"
            ),
            progress_callback=on_progress,
        )
        usages = [
            item
            for item in pipeline.reference_library.list_usage(args.project_id, args.node_id)
            if str(item.get("id") or "") not in existing_usage_ids
        ]
    finally:
        vector_index.close()

    traces = []
    for path in sorted(trace_dir.glob("*.json")):
        item = json.loads(path.read_text(encoding="utf-8"))
        traces.append({
            "path": str(path),
            "schema_name": item.get("schema_name"),
            "elapsed_seconds": item.get("elapsed_seconds"),
            "usage": item.get("usage"),
            "error": item.get("error"),
        })
    usage_totals: dict[str, int] = {}
    for trace in traces:
        for key, value in (trace.get("usage") or {}).items():
            usage_totals[key] = usage_totals.get(key, 0) + int(value)
    payload = {
        "project_id": args.project_id,
        "node_id": args.node_id,
        "model": args.model,
        "draft": dump_model(draft),
        "reference_atom_usages": usages,
        "progress": progress,
        "trace_count": len(traces),
        "usage_totals": usage_totals,
        "traces": traces,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "draft_id": draft.id,
        "title": draft.title,
        "markdown_characters": len(draft.markdown),
        "reference_atom_usage_count": len(usages),
        "trace_count": len(traces),
        "usage_totals": usage_totals,
        "output": str(args.output),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
