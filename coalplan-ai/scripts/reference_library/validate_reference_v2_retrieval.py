from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from coalplan.application.hybrid_atom_retrieval import (
    build_query_text,
    hybrid_prefilter_atoms,
    query_filters,
)
from coalplan.application.reference_atom_query import QueryClassification, classify_atom_retrieval_query
from coalplan.application.serialization import dump_model
from coalplan.domain.reference_library import AtomRetrievalQuery
from coalplan.infrastructure.database.reference_repository import ReferenceLibraryRepository
from coalplan.infrastructure.database.session import create_session_factory, init_database, sqlite_url_for_storage
from coalplan.infrastructure.llm.codex_cli import CodexCliStructuredLLMClient
from coalplan.infrastructure.vector.qdrant_atom_index import QdrantAtomVectorIndex, SentenceTransformerEmbedder
from coalplan.settings import get_settings


SAMPLE_QUERIES = [
    AtomRetrievalQuery(
        project_name="雅砻江两河口水电站库区复建县道测试项目",
        project_type="水电站库区复建道路工程",
        chapter_title="隧洞钻爆开挖施工",
        parent_titles=["主要施工方法", "隧洞工程"],
        evidence_summary="洞口浅埋，局部岩体破碎，需组织钻孔、装药联网、爆破、通风排烟、出渣和初期支护；投标资料未确认具体孔距和装药量。",
        writing_topics=["工艺流程", "钻孔质量", "装药联网", "爆后检查", "通风排烟", "质量安全控制"],
        top_k=5,
    ),
    AtomRetrievalQuery(
        project_name="水电枢纽混凝土坝测试项目",
        project_type="水利水电枢纽工程",
        chapter_title="大坝混凝土温控与养护",
        parent_titles=["主体工程施工", "混凝土工程"],
        evidence_summary="大体积混凝土分层分仓浇筑，需要覆盖入仓温度、冷却水管、通水冷却、表面保温、养护和温度监测闭环；具体温控参数待设计文件确认。",
        writing_topics=["温控设计", "通水冷却", "保温养护", "温度监测", "异常处置"],
        top_k=5,
    ),
    AtomRetrievalQuery(
        project_name="引水隧洞固结灌浆测试项目",
        project_type="水利水电地下洞室工程",
        chapter_title="引水隧洞固结灌浆施工",
        parent_titles=["灌浆工程", "固结灌浆"],
        evidence_summary="围岩固结灌浆需要组织孔位放样、钻孔冲洗、压水试验、分序分段灌浆、封孔和质量检查；压力、浆液配比和结束标准须由当前设计或试验确定。",
        writing_topics=["施工程序", "钻孔冲洗", "压水试验", "灌浆控制", "结束标准", "质量检查"],
        top_k=5,
    ),
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="gpt-5.6-luna")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--reuse-classifications", type=Path)
    args = parser.parse_args()

    settings = get_settings()
    storage = settings.storage_dir.resolve()
    factory = create_session_factory(settings.database_url or sqlite_url_for_storage(storage))
    init_database(factory)
    repository = ReferenceLibraryRepository(factory)
    trace_dir = args.output.parent / "retrieval-validation-traces"

    source_queries = SAMPLE_QUERIES
    if args.reuse_classifications:
        saved = json.loads(args.reuse_classifications.read_text(encoding="utf-8"))
        source_queries = [AtomRetrievalQuery(**item["input_query"]) for item in saved["scenarios"]]
        classifications = [
            QueryClassification(
                query=AtomRetrievalQuery(**item["classified_query"]),
                confidence=float(item["classification_confidence"]),
                reason=item["classification_reason"],
            )
            for item in saved["scenarios"]
        ]
    else:
        def classify(query: AtomRetrievalQuery):
            client = CodexCliStructuredLLMClient(
                model=args.model,
                workdir=Path.cwd(),
                trace_dir=trace_dir,
                timeout=args.timeout,
            )
            return classify_atom_retrieval_query(query, llm=client)

        with ThreadPoolExecutor(max_workers=len(source_queries)) as executor:
            classifications = list(executor.map(classify, source_queries))

    embedder = SentenceTransformerEmbedder(settings.reference_vector_model)
    vector_path = settings.reference_vector_path
    if not vector_path.is_absolute():
        vector_path = storage / vector_path
    vector_index = QdrantAtomVectorIndex(
        embed=embedder,
        dimension=embedder.dimension,
        url=settings.reference_vector_url,
        path=vector_path,
    )
    scenarios = []
    try:
        for source_query, classification in zip(source_queries, classifications, strict=True):
            query = classification.query
            vector_results = vector_index.search(
                build_query_text(query),
                limit=max(12, query.top_k * 4),
                filters=query_filters(query),
            )
            atoms = repository.list_v2_retrieval_candidates(query, limit=max(100, query.top_k * 20))
            loaded = {atom.id for atom in atoms}
            atoms.extend(repository.get_atoms([atom_id for atom_id, _ in vector_results if atom_id not in loaded]))
            candidates = hybrid_prefilter_atoms(
                atoms,
                query,
                vector_results=vector_results,
                limit=query.top_k,
            )
            scenarios.append({
                "input_query": dump_model(source_query),
                "classified_query": dump_model(query),
                "classification_confidence": classification.confidence,
                "classification_reason": classification.reason,
                "results": [
                    {
                        "atom_id": item.atom.id,
                        "source_document_id": item.atom.document_id,
                        "source_project": item.atom.project_name,
                        "source_title_path": item.atom.title_path,
                        "score": round(item.score, 6),
                        "lexical_rank": item.lexical_rank,
                        "vector_rank": item.vector_rank,
                        "match_reasons": item.match_reasons,
                        "engineering_object": item.atom.engineering_object,
                        "process_family": item.atom.process_family,
                        "parameterized_template": item.atom.parameterized_template,
                        "parameter_slots": [dump_model(slot) for slot in item.atom.parameter_slots],
                    }
                    for item in candidates
                ],
            })
    finally:
        vector_index.close()

    payload = {"model": args.model, "scenario_count": len(scenarios), "scenarios": scenarios}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "scenario_count": len(scenarios),
        "result_counts": [len(item["results"]) for item in scenarios],
        "output": str(args.output),
        "trace_dir": str(trace_dir),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
