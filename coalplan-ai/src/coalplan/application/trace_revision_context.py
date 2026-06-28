from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field


TraceFactStatus = Literal["not_prompted", "prompted_but_omitted", "absorbed_in_response"]


class TraceRevisionFact(BaseModel):
    fact: str
    status: TraceFactStatus
    suggested_action: str = ""
    kind: str | None = None
    line: int | None = None
    context: str | None = None
    prompt_trace_files: list[str] = Field(default_factory=list)
    response_trace_files: list[str] = Field(default_factory=list)

    @property
    def label(self) -> str:
        action = self.suggested_action or _default_action(self.status)
        return f"{self.fact} [{self.status} -> {action}]"


class TraceRevisionContext(BaseModel):
    project_key: str | None = None
    trace_count: int = 0
    remap_facts: list[TraceRevisionFact] = Field(default_factory=list)
    required_generation_facts: list[TraceRevisionFact] = Field(default_factory=list)
    accepted_facts: list[TraceRevisionFact] = Field(default_factory=list)

    @property
    def has_actions(self) -> bool:
        return bool(self.remap_facts or self.required_generation_facts)


def build_trace_revision_context(
    trace_diagnostics: dict[str, Any] | None,
    *,
    source_text: str = "",
    max_items: int = 12,
) -> TraceRevisionContext:
    """Convert trace diagnostics into explicit next-run mapping/generation controls."""

    if not trace_diagnostics:
        return TraceRevisionContext()
    context = TraceRevisionContext(
        project_key=trace_diagnostics.get("project_key"),
        trace_count=int(trace_diagnostics.get("trace_count") or 0),
    )
    for raw in trace_diagnostics.get("facts") or []:
        fact = _fact_from_raw(raw)
        if fact is None:
            continue
        if fact.status == "not_prompted":
            context.remap_facts.append(fact)
            if source_text and _fact_supported_by_source(fact.fact, source_text):
                context.required_generation_facts.append(fact)
        elif fact.status == "prompted_but_omitted":
            if not source_text or _fact_supported_by_source(fact.fact, source_text):
                context.required_generation_facts.append(fact)
            else:
                context.remap_facts.append(fact)
        elif fact.status == "absorbed_in_response":
            context.accepted_facts.append(fact)
        if len(context.remap_facts) >= max_items and len(context.required_generation_facts) >= max_items:
            break
    context.remap_facts = _dedupe_facts(context.remap_facts)[:max_items]
    context.required_generation_facts = _dedupe_facts(context.required_generation_facts)[:max_items]
    context.accepted_facts = _dedupe_facts(context.accepted_facts)[:max_items]
    return context


def build_trace_revision_context_from_labels(
    labels: list[str],
    *,
    project_key: str | None = None,
    source_text: str = "",
    max_items: int = 12,
) -> TraceRevisionContext:
    facts = []
    for label in labels:
        parsed = parse_trace_fact_label(label)
        if parsed is None:
            facts.append({"fact": str(label), "status": "prompted_but_omitted", "suggested_action": "regenerate"})
            continue
        fact, status, action = parsed
        facts.append({"fact": fact, "status": status, "suggested_action": action})
    return build_trace_revision_context(
        {"project_key": project_key, "facts": facts},
        source_text=source_text,
        max_items=max_items,
    )


def render_trace_mapping_context(context: TraceRevisionContext, *, max_items: int = 12) -> str:
    if not context.remap_facts:
        return ""
    lines = [
        "## Trace Revision Mapping Requirements",
        "- These facts were lost before or during previous prompting.",
        "- Use them only as source-selection hints; do not invent unsupported facts.",
        "- If no source section supports a fact, return it in missing_evidence.",
        "",
        "### Facts Requiring Source Remap",
    ]
    lines.extend(f"- {fact.label}" for fact in context.remap_facts[:max_items])
    return "\n".join(lines).strip()


def render_trace_generation_context(context: TraceRevisionContext, *, max_items: int = 12) -> str:
    if not context.required_generation_facts:
        return ""
    lines = [
        "## Trace Revision Generation Requirements",
        "- These source-supported facts were omitted in an earlier generation attempt.",
        "- If a fact is in the current chapter scope, write it into `## 生成正文`.",
        "- If it is out of scope or still unsupported, explain it under `## 人工补充需补充`.",
        "",
        "### Required Source-Supported Facts",
    ]
    lines.extend(f"- {fact.label}" for fact in context.required_generation_facts[:max_items])
    return "\n".join(lines).strip()


def parse_trace_fact_label(label: str) -> tuple[str, TraceFactStatus, str] | None:
    match = re.match(
        r"^(?P<fact>.*?)\s*\[(?P<status>not_prompted|prompted_but_omitted|absorbed_in_response)\s*->\s*(?P<action>[^]]+)\]\s*$",
        str(label).strip(),
    )
    if not match:
        return None
    return (
        match.group("fact").strip(),
        match.group("status"),  # type: ignore[return-value]
        match.group("action").strip(),
    )


def strip_trace_fact_label(label: str) -> str:
    parsed = parse_trace_fact_label(label)
    return parsed[0] if parsed else str(label).strip()


def _fact_from_raw(raw: Any) -> TraceRevisionFact | None:
    if isinstance(raw, str):
        parsed = parse_trace_fact_label(raw)
        if parsed is None:
            return TraceRevisionFact(fact=raw.strip(), status="prompted_but_omitted", suggested_action="regenerate")
        fact, status, action = parsed
        return TraceRevisionFact(fact=fact, status=status, suggested_action=action)
    if not isinstance(raw, dict):
        return None
    fact = str(raw.get("fact") or "").strip()
    status = str(raw.get("status") or "").strip()
    if not fact or status not in {"not_prompted", "prompted_but_omitted", "absorbed_in_response"}:
        return None
    return TraceRevisionFact(
        fact=fact,
        status=status,  # type: ignore[arg-type]
        suggested_action=str(raw.get("suggested_action") or _default_action(status)).strip(),
        kind=raw.get("kind"),
        line=_int_or_none(raw.get("line")),
        context=raw.get("context"),
        prompt_trace_files=[str(item) for item in raw.get("prompt_trace_files") or []],
        response_trace_files=[str(item) for item in raw.get("response_trace_files") or []],
    )


def _default_action(status: str) -> str:
    if status == "not_prompted":
        return "remap_sources"
    if status == "prompted_but_omitted":
        return "regenerate"
    return "accept"


def _dedupe_facts(facts: list[TraceRevisionFact]) -> list[TraceRevisionFact]:
    output: list[TraceRevisionFact] = []
    seen: set[tuple[str, str]] = set()
    for fact in facts:
        key = (_normalize_fact_match_text(fact.fact), fact.status)
        if key in seen:
            continue
        seen.add(key)
        output.append(fact)
    return output


def _fact_supported_by_source(fact: str, source_text: str) -> bool:
    normalized_source = _normalize_fact_match_text(source_text)
    tokens = _fact_hint_tokens(fact)
    if not tokens:
        return _normalize_fact_match_text(fact) in normalized_source
    numeric_or_standard = [token for token in tokens if any(char.isdigit() for char in token)]
    if numeric_or_standard:
        return any(_normalize_fact_match_text(token) in normalized_source for token in numeric_or_standard)
    return sum(1 for token in tokens if _normalize_fact_match_text(token) in normalized_source) >= min(2, len(tokens))


def _fact_hint_tokens(text: str) -> list[str]:
    tokens: list[str] = []
    for token in re.findall(r"(?:GB/T|GB|DL/T|JGJ|SL|DZ/T|HJ|NB/T|TB|JTJ|JTG)\s*[-A-Z0-9./]+", text, flags=re.I):
        if token not in tokens:
            tokens.append(token)
    for token in re.findall(
        r"\d+(?:\.\d+)?(?:\s*(?:-|~|至|～)\s*\d+(?:\.\d+)?)?\s*"
        r"(?:m3/min|m3|m2|mm|cm|km|m|t|kg|MPa|kPa|kN|kW|MW|%|℃|天|日|月|年)",
        text,
        flags=re.I,
    ):
        if token not in tokens:
            tokens.append(token)
    if tokens:
        return tokens[:8]
    for token in re.findall(r"[\u4e00-\u9fff]{2,12}", text):
        if token not in tokens:
            tokens.append(token)
    return tokens[:8]


def _normalize_fact_match_text(text: str) -> str:
    return re.sub(r"\s+", "", text or "").lower()


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
