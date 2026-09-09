from __future__ import annotations

import json
from dataclasses import dataclass

from coalplan.application.reference_atomization_v2 import load_reference_taxonomy
from coalplan.domain.reference_library import AtomRetrievalQuery
from coalplan.ports.llm import StructuredLLMClient


@dataclass(frozen=True)
class QueryClassification:
    query: AtomRetrievalQuery
    confidence: float
    reason: str


def classify_atom_retrieval_query(
    query: AtomRetrievalQuery,
    *,
    llm: StructuredLLMClient,
    taxonomy: dict | None = None,
) -> QueryClassification:
    taxonomy = taxonomy or load_reference_taxonomy()
    payload = llm.complete_json(_prompt(query, taxonomy), schema_name="reference_atom_query_v2")
    updated = query.model_copy(deep=True)
    _fill_controlled(updated, "chapter_module", payload, taxonomy["chapter_modules"])
    _fill_controlled(updated, "engineering_system", payload, taxonomy["engineering_systems"])
    _fill_controlled(updated, "process_family", payload, taxonomy["process_families"])
    _fill_controlled(updated, "process_stage", payload, taxonomy["process_stages"])
    if not updated.engineering_object:
        updated.engineering_object = str(payload.get("engineering_object", "")).strip()
    if not updated.content_functions:
        updated.content_functions = [
            str(item) for item in payload.get("content_functions", [])
            if str(item) in taxonomy["content_functions"]
        ]
    if not updated.applicability:
        updated.applicability = [str(item).strip() for item in payload.get("applicability", []) if str(item).strip()]
    return QueryClassification(updated, _score(payload.get("confidence")), str(payload.get("reason", "")).strip())


def _prompt(query: AtomRetrievalQuery, taxonomy: dict) -> str:
    return f"""你负责把施工组织设计章节的检索意图映射到受控原子标签，不负责生成正文。
请同时考虑项目全局信息、目录上下文、当前章节、局部投标证据和写作任务。
已有非空标签是用户或上游确认值，不要提出替代。

受控标签：
- chapter_module: {json.dumps(taxonomy['chapter_modules'], ensure_ascii=False)}
- engineering_system: {json.dumps(taxonomy['engineering_systems'], ensure_ascii=False)}
- process_family: {json.dumps(taxonomy['process_families'], ensure_ascii=False)}
- process_stage: {json.dumps(taxonomy['process_stages'], ensure_ascii=False)}
- content_functions: {json.dumps(taxonomy['content_functions'], ensure_ascii=False)}

返回 JSON：
{{"chapter_module":"","engineering_system":"","engineering_object":"","process_family":"","process_stage":"","content_functions":[],"applicability":[],"confidence":0.0,"reason":""}}

检索上下文：
{json.dumps(query.model_dump(mode='json'), ensure_ascii=False)}"""


def _fill_controlled(query: AtomRetrievalQuery, field: str, payload: dict, allowed: list[str]) -> None:
    if getattr(query, field):
        return
    value = str(payload.get(field, "")).strip()
    if value in allowed:
        setattr(query, field, value)


def _score(value) -> float:
    try:
        return min(1.0, max(0.0, float(value)))
    except (TypeError, ValueError):
        return 0.0
