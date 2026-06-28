from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


def diagnose_trace_evidence_absorption(
    *,
    quality_report: dict[str, Any],
    trace_dir: str | Path,
    max_examples: int = 30,
) -> dict[str, Any]:
    """Explain whether omitted source facts reached LLM prompts or were lost earlier.

    The quality audit can tell that a generated document omitted a source fact. This
    diagnostic separates two different control actions:

    - fact absent from prompts: remap sources or increase evidence budget;
    - fact present in prompts but absent from responses: regenerate with fact carryover.
    """

    traces = load_llm_traces(trace_dir)
    facts = _omitted_facts_from_report(quality_report)[:max_examples]
    fact_results = [_diagnose_fact(fact, traces) for fact in facts]
    buckets = _bucket_counts(fact_results)
    recommended_actions = _recommended_actions(buckets)
    return {
        "project_key": quality_report.get("project_key"),
        "trace_dir": str(Path(trace_dir)),
        "trace_count": len(traces),
        "omitted_fact_count": len(facts),
        "buckets": buckets,
        "facts": fact_results,
        "recommended_actions": recommended_actions,
    }


def load_llm_traces(trace_dir: str | Path) -> list[dict[str, Any]]:
    path = Path(trace_dir)
    if not path.exists():
        raise FileNotFoundError(f"Trace directory not found: {path}")
    traces: list[dict[str, Any]] = []
    for item in sorted(path.glob("*.json")):
        try:
            payload = json.loads(item.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        traces.append(
            {
                "trace_file": item.name,
                "kind": payload.get("kind"),
                "schema_name": payload.get("schema_name"),
                "prompt": payload.get("prompt") or "",
                "response": payload.get("response") or "",
                "error": payload.get("error"),
            }
        )
    return traces


def render_trace_evidence_diagnostics_markdown(report: dict[str, Any]) -> str:
    lines = [
        f"# Trace Evidence Diagnostics: {report.get('project_key') or '-'}",
        "",
        "## Summary",
        f"- trace_dir: `{report.get('trace_dir')}`",
        f"- trace_count: {report.get('trace_count', 0)}",
        f"- omitted_fact_count: {report.get('omitted_fact_count', 0)}",
        "",
        "## Buckets",
    ]
    for key, value in (report.get("buckets") or {}).items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Recommended Actions"])
    actions = report.get("recommended_actions") or []
    if actions:
        for action in actions:
            lines.extend(
                [
                    f"### {action['action']}",
                    f"- severity: {action['severity']}",
                    f"- reason: {action['reason']}",
                    "- next_steps:",
                    *[f"  - {step}" for step in action["next_steps"]],
                    "",
                ]
            )
    else:
        lines.append("- No trace-specific action.")
    lines.extend(["", "## Fact Diagnostics"])
    for item in report.get("facts") or []:
        lines.append(
            f"- `{item['fact']}`: {item['status']}; "
            f"prompt_hits={item['prompt_hit_count']}; response_hits={item['response_hit_count']}; "
            f"suggested_action={item['suggested_action']}"
        )
        for trace in item.get("sample_traces", [])[:3]:
            lines.append(
                f"  - {trace['trace_file']}: prompt={trace['in_prompt']}, response={trace['in_response']}, "
                f"title_hint={trace.get('title_hint') or '-'}"
            )
    return "\n".join(lines).strip() + "\n"


def _diagnose_fact(fact_item: dict[str, Any], traces: list[dict[str, Any]]) -> dict[str, Any]:
    fact = str(fact_item.get("fact") or fact_item).strip()
    prompt_hits = []
    response_hits = []
    samples = []
    for trace in traces:
        in_prompt = _contains_fact(trace["prompt"], fact)
        in_response = _contains_fact(trace["response"], fact)
        if in_prompt:
            prompt_hits.append(trace["trace_file"])
        if in_response:
            response_hits.append(trace["trace_file"])
        if in_prompt or in_response:
            samples.append(
                {
                    "trace_file": trace["trace_file"],
                    "kind": trace.get("kind"),
                    "schema_name": trace.get("schema_name"),
                    "in_prompt": in_prompt,
                    "in_response": in_response,
                    "title_hint": _title_hint(trace["prompt"]),
                }
            )
    if response_hits:
        status = "absorbed_in_response"
        suggested_action = "accept"
        reason = "The fact appears in at least one LLM response; the final audit may be document-scope or merge-scope."
    elif prompt_hits:
        status = "prompted_but_omitted"
        suggested_action = "regenerate"
        reason = "The fact reached the prompt but disappeared from the response."
    else:
        status = "not_prompted"
        suggested_action = "remap_sources"
        reason = "The fact did not reach any prompt in the trace directory."
    return {
        "fact": fact,
        "kind": fact_item.get("kind"),
        "line": fact_item.get("line"),
        "context": fact_item.get("context"),
        "status": status,
        "suggested_action": suggested_action,
        "reason": reason,
        "prompt_hit_count": len(prompt_hits),
        "response_hit_count": len(response_hits),
        "prompt_trace_files": prompt_hits[:12],
        "response_trace_files": response_hits[:12],
        "sample_traces": samples[:5],
    }


def _omitted_facts_from_report(report: dict[str, Any]) -> list[dict[str, Any]]:
    source_facts = report.get("source_facts") or {}
    facts = source_facts.get("omitted_examples") or []
    return [item if isinstance(item, dict) else {"fact": str(item)} for item in facts if item]


def _bucket_counts(items: list[dict[str, Any]]) -> dict[str, int]:
    buckets = {
        "not_prompted": 0,
        "prompted_but_omitted": 0,
        "absorbed_in_response": 0,
    }
    for item in items:
        status = item.get("status")
        if status in buckets:
            buckets[status] += 1
    return buckets


def _recommended_actions(buckets: dict[str, int]) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    if buckets.get("not_prompted", 0):
        actions.append(
            {
                "action": "remap_sources",
                "severity": "warning",
                "reason": f"{buckets['not_prompted']} omitted fact(s) never reached LLM prompts.",
                "next_steps": [
                    "Re-run source mapping with omitted facts as mapping hints.",
                    "Increase max_source_matches and max_evidence_spans for affected chapters.",
                    "If no matching source section exists, route the item to human input.",
                ],
            }
        )
    if buckets.get("prompted_but_omitted", 0):
        actions.append(
            {
                "action": "regenerate",
                "severity": "warning",
                "reason": f"{buckets['prompted_but_omitted']} omitted fact(s) reached prompts but were not in responses.",
                "next_steps": [
                    "Add these facts to required_source_facts in the revision context.",
                    "Require the next response to use each fact in the正文 or explain why it is out of scope.",
                    "Fail validation if the same fact is omitted again without a missing-source reason.",
                ],
            }
        )
    return actions


def _contains_fact(text: str, fact: str) -> bool:
    if not text or not fact:
        return False
    if fact in text:
        return True
    normalized_text = _normalize_fact(text)
    normalized_fact = _normalize_fact(fact)
    return bool(normalized_fact and normalized_fact in normalized_text)


def _normalize_fact(text: str) -> str:
    return re.sub(r"\s+", "", text or "").replace("～", "-").replace("~", "-").lower()


def _title_hint(prompt: str) -> str:
    if not prompt:
        return ""
    patterns = [
        r"期望标题[：:]\s*(?P<title>[^\n]+)",
        r"#\s*(?P<title>本章目标字数|[^\n]{2,80})",
        r'"title"\s*:\s*"(?P<title>[^"]+)"',
    ]
    for pattern in patterns:
        match = re.search(pattern, prompt)
        if match:
            return " ".join(match.group("title").split())[:120]
    return ""
