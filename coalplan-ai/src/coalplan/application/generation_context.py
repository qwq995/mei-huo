from __future__ import annotations

import re
from datetime import datetime

from coalplan.application.serialization import dump_model, to_json_text
from coalplan.domain.generation import ChapterDraft
from coalplan.domain.generation_context import ChapterRollingSummary, GenerationContextState, WritingUnitTrace
from coalplan.domain.outline import TemplateOutlinePlan
from coalplan.domain.profile import ProjectProfile
from coalplan.domain.templates import TemplateNode
from coalplan.ports.llm import StructuredLLMClient


MAX_CONTEXT_ITEMS = 30


def initialize_generation_context(
    *,
    profile: ProjectProfile,
    outline: TemplateOutlinePlan | None,
    existing: GenerationContextState | None = None,
) -> GenerationContextState:
    state = existing or GenerationContextState()
    if not state.project_overview:
        outline_overview = outline.project_summary.overview if outline else ""
        state.project_overview = outline_overview or "；".join(
            item for item in [profile.project_name, profile.project_type, profile.location] if item
        )
    state.construction_scope = _merge_bounded(state.construction_scope, profile.construction_scope)
    state.unresolved_items = _merge_bounded(state.unresolved_items, profile.missing_items)
    return state


def render_generation_context_for_prompt(
    state: GenerationContextState | None,
    *,
    current_node_id: str,
) -> str:
    if state is None:
        return "尚无已生成章节的滚动概括。"
    completed = [
        summary
        for node_id in state.generated_node_order[-10:]
        if node_id != current_node_id and (summary := state.chapter_summaries.get(node_id)) is not None
    ]
    payload = {
        "project_overview": state.project_overview,
        "construction_scope": state.construction_scope[:12],
        "confirmed_global_facts": state.confirmed_global_facts[:20],
        "terminology": state.terminology[:20],
        "construction_interfaces": state.construction_interfaces[:20],
        "unresolved_items": state.unresolved_items[:20],
        "completed_chapters": [
            {
                "node_id": item.node_id,
                "title": item.title,
                "overview": item.overview,
                "established_facts": item.established_facts[:8],
                "interfaces": item.interfaces[:6],
                "terminology": item.terminology[:8],
                "unresolved_items": item.unresolved_items[:6],
            }
            for item in completed
        ],
    }
    return to_json_text(payload)


def update_generation_context(
    *,
    state: GenerationContextState,
    node: TemplateNode,
    draft: ChapterDraft,
    writing_units: list[WritingUnitTrace],
    reference_atom_ids: list[str],
    llm: StructuredLLMClient,
    trusted_project_text: str = "",
) -> tuple[GenerationContextState, ChapterRollingSummary]:
    fallback = _fallback_chapter_summary(
        node=node,
        draft=draft,
        writing_units=writing_units,
        reference_atom_ids=reference_atom_ids,
    )
    summary = fallback
    updates: dict = {}
    try:
        payload = llm.complete_json(
            _context_update_prompt(
                state=state,
                node=node,
                draft=draft,
                fallback=fallback,
                trusted_project_text=trusted_project_text,
            ),
            schema_name="GenerationContextUpdate",
        )
        candidate = ChapterRollingSummary(
            node_id=node.id,
            title=node.title,
            status="generated" if draft.validation_status.value == "passed" else "needs_repair",
            **(payload.get("chapter_summary") or {}),
            source_section_ids=draft.source_section_ids,
            reference_atom_ids=reference_atom_ids,
            writing_unit_ids=[item.unit_id for item in writing_units],
        )
        if candidate.overview:
            summary = _validate_summary(candidate, draft.markdown, trusted_project_text, fallback)
        updates = payload.get("global_updates") or {}
    except Exception:
        pass

    state.chapter_summaries[node.id] = summary
    if node.id in state.generated_node_order:
        state.generated_node_order.remove(node.id)
    state.generated_node_order.append(node.id)
    state.confirmed_global_facts = _merge_supported(
        state.confirmed_global_facts,
        updates.get("confirmed_global_facts", []),
        trusted_project_text,
    )
    state.terminology = _merge_supported(state.terminology, updates.get("terminology", []), draft.markdown)
    state.construction_interfaces = _merge_bounded(
        state.construction_interfaces,
        _supported_items(summary.interfaces, trusted_project_text),
        _supported_items(updates.get("construction_interfaces", []), trusted_project_text),
    )
    state.unresolved_items = _merge_bounded(
        state.unresolved_items,
        summary.unresolved_items,
        updates.get("unresolved_items", []),
    )
    state.updated_at = datetime.now().isoformat(timespec="seconds")
    return state, summary


def chapter_summary_patch(summary: ChapterRollingSummary, existing: dict | None = None) -> dict:
    payload = dict(existing or {})
    payload.update(
        {
            "generated_overview": summary.overview,
            "established_facts": summary.established_facts,
            "interfaces": summary.interfaces,
            "terminology": summary.terminology,
            "unresolved_items": summary.unresolved_items,
            "reference_atom_ids": summary.reference_atom_ids,
            "updated_at": summary.updated_at,
        }
    )
    return payload


def _context_update_prompt(
    *,
    state: GenerationContextState,
    node: TemplateNode,
    draft: ChapterDraft,
    fallback: ChapterRollingSummary,
    trusted_project_text: str,
) -> str:
    return "\n".join(
        [
            "你负责维护施工组织设计的跨章节滚动概括。只压缩已经生成的当前项目内容，不新增事实。",
            "",
            "既有全局上下文：",
            render_generation_context_for_prompt(state, current_node_id=node.id),
            "",
            "当前章节：",
            f"{node.id} / {node.title}",
            "",
            "当前章节 Markdown：",
            draft.markdown[:12000],
            "",
            "当前章节可信投标证据（事实校验源）：",
            trusted_project_text[:12000] or "无可信投标证据。",
            "",
            "保底概括：",
            to_json_text(dump_model(fallback)),
            "",
            "返回 JSON：",
            '{"chapter_summary":{"overview":"","established_facts":[],"decisions":[],"interfaces":[],"terminology":[],"unresolved_items":[]},"global_updates":{"confirmed_global_facts":[],"terminology":[],"construction_interfaces":[],"unresolved_items":[]}}',
            "",
            "规则：",
            "- overview 用 1~3 句概括本章已实际写入的内容。",
            "- established_facts 必须同时能在可信投标证据中找到支持；生成正文不能给自身作事实证明。",
            "- interfaces 记录投标证据已支持的跨章节工序、组织、资料接口和约束。",
            "- terminology 记录后续章节应保持一致的工程对象、工法和专业称谓。",
            "- unresolved_items 保留人工补充项和仍待确认的参数。",
            "- 全局更新必须能在当前章节中找到依据；不要重复已有内容。",
        ]
    )


def _fallback_chapter_summary(
    *,
    node: TemplateNode,
    draft: ChapterDraft,
    writing_units: list[WritingUnitTrace],
    reference_atom_ids: list[str],
) -> ChapterRollingSummary:
    body = _module(draft.markdown, "生成正文")
    overview = _compact_text(body, 360) or f"已生成“{node.title}”章节。"
    unresolved = [
        _compact_text(item, 180)
        for item in re.findall(r"【需人工补充：?(.*?)】", draft.markdown)
        if _compact_text(item, 180)
    ]
    terminology = _candidate_terminology(node.title, body)
    return ChapterRollingSummary(
        node_id=node.id,
        title=node.title,
        status="generated" if draft.validation_status.value == "passed" else "needs_repair",
        overview=overview,
        terminology=terminology,
        unresolved_items=list(dict.fromkeys(unresolved))[:12],
        source_section_ids=draft.source_section_ids,
        reference_atom_ids=reference_atom_ids,
        writing_unit_ids=[item.unit_id for item in writing_units],
    )


def _validate_summary(
    candidate: ChapterRollingSummary,
    markdown: str,
    trusted_project_text: str,
    fallback: ChapterRollingSummary,
) -> ChapterRollingSummary:
    candidate.established_facts = _supported_items(candidate.established_facts, trusted_project_text)
    candidate.terminology = _supported_items(candidate.terminology, markdown)
    candidate.decisions = _supported_items(candidate.decisions, markdown)
    candidate.interfaces = _supported_items(candidate.interfaces, trusted_project_text)
    candidate.unresolved_items = _merge_bounded(fallback.unresolved_items, candidate.unresolved_items)
    candidate.updated_at = datetime.now().isoformat(timespec="seconds")
    return candidate


def _supported_items(items: list[str], source: str) -> list[str]:
    output: list[str] = []
    normalized_source = _normalize(source)
    for item in items:
        text = str(item).strip()
        tokens = re.findall(r"[\u4e00-\u9fff]{2,8}|[A-Za-z]{2,}|\d+(?:\.\d+)?", text)
        specific = [token for token in tokens if len(token) >= 2]
        if text and (not specific or sum(_normalize(token) in normalized_source for token in specific) >= max(1, len(specific) // 2)):
            output.append(text)
    return _bounded(output)


def _merge_supported(existing: list[str], additions: list[str], source: str) -> list[str]:
    return _merge_bounded(existing, _supported_items([str(item) for item in additions], source))


def _merge_bounded(*groups: list[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for item in group or []:
            text = str(item).strip()
            key = _normalize(text)
            if not key or key in seen:
                continue
            seen.add(key)
            output.append(text)
            if len(output) >= MAX_CONTEXT_ITEMS:
                return output
    return output


def _bounded(items: list[str]) -> list[str]:
    return _merge_bounded(items)


def _module(markdown: str, title: str) -> str:
    match = re.search(rf"^##\s+{re.escape(title)}\s*$\n(.*?)(?=^##\s+|\Z)", markdown, flags=re.M | re.S)
    return match.group(1).strip() if match else markdown


def _compact_text(value: str, limit: int) -> str:
    text = re.sub(r"[#*`>|]", " ", value or "")
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= limit else text[:limit].rstrip() + "…"


def _candidate_terminology(title: str, body: str) -> list[str]:
    candidates = [title]
    candidates.extend(re.findall(r"(?:地下洞室|导流隧洞|尾水洞|喷射混凝土|衬砌混凝土|钻孔爆破|帷幕灌浆|回填灌浆|施工导流)", body))
    return list(dict.fromkeys(candidates))[:12]


def _normalize(value: str) -> str:
    return re.sub(r"\s+", "", value or "").lower()
