from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import Any

from coalplan.application.organization_pattern_audit import audit_document_organization
from coalplan.application.serialization import dump_model
from coalplan.application.word_count_targets import count_words


COMMON_TOPIC_TERMS = {
    "overview": ("工程概况", "项目概况", "工程范围", "主要工程量", "施工条件"),
    "deployment": ("施工部署", "组织机构", "施工总平面", "临建", "施工准备"),
    "schedule_resource": ("施工进度", "工期", "资源配置", "劳动力", "机械设备", "材料"),
    "craft": ("施工方法", "施工工艺", "施工程序", "工艺流程", "质量检查", "验收"),
    "quality": ("质量目标", "质量保证", "质量控制", "检验", "试验", "验收"),
    "safety": ("安全目标", "安全保证", "危险源", "应急", "职业健康"),
    "environment": ("环境保护", "水土保持", "文明施工", "扬尘", "噪声", "废水"),
}

FACT_RE = re.compile(
    r"(?P<value>\d+(?:\.\d+)?(?:\s*(?:-|~|～|至)\s*\d+(?:\.\d+)?)?\s*"
    r"(?P<unit>m3/min|m³/min|m3|m³|m2|m²|mm|cm|km|m|t|kg|MPa|kPa|kN|kW|MW|%|℃|"
    r"天|日|月|年|个|座|台|套|根|孔|条|项|处|人|小时|分钟|万元|亿元))"
)
STANDARD_RE = re.compile(r"\b(?:GB|GB/T|DL/T|JGJ|SL|DZ/T|HJ|NB/T|TB|JTJ|JTG)\s*[-A-Z0-9./]+\b", re.I)
HEADING_RE = re.compile(r"^\s{0,3}(?:#{1,6}\s+)?(?P<title>.+?)\s*$")
MARKDOWN_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(?P<title>.+?)\s*$")
NUMBERED_HEADING_RE = re.compile(
    r"^\s*(?:第[一二三四五六七八九十百]+[章节篇]|[一二三四五六七八九十]+[、.．]|"
    r"\d+(?:\.\d+){0,5}[、.．]?)\s*(?P<title>[\u4e00-\u9fffA-Za-z0-9（）()《》、\-—/ ]{2,80})\s*$"
)


@dataclass(frozen=True)
class QualityAuditInput:
    project_key: str
    generated_markdown: str
    source_markdown: str = ""
    human_markdown: str = ""


def audit_generation_quality(data: QualityAuditInput) -> dict[str, Any]:
    generated = data.generated_markdown or ""
    source = data.source_markdown or ""
    human = data.human_markdown or ""
    generated_headings = extract_headings(generated)
    human_headings = extract_headings(human)
    source_facts = extract_high_value_facts(source)
    fact_audit = audit_fact_absorption(generated, source_facts)
    topic_audit = audit_common_topics(generated)
    heading_audit = audit_heading_overlap(generated_headings, human_headings)
    organization_audit = audit_document_organization(
        generated,
        source_markdown=source,
        human_markdown=human,
    )

    generated_words = count_words(generated)
    human_words = count_words(human) if human else 0
    source_words = count_words(source) if source else 0
    issues = _quality_issues(
        generated_words=generated_words,
        human_words=human_words,
        heading_audit=heading_audit,
        fact_audit=fact_audit,
        topic_audit=topic_audit,
        organization_audit=dump_model(organization_audit),
    )
    recommendations = _quality_recommendations(
        generated_words=generated_words,
        human_words=human_words,
        heading_audit=heading_audit,
        fact_audit=fact_audit,
        topic_audit=topic_audit,
        organization_audit=dump_model(organization_audit),
    )
    return {
        "project_key": data.project_key,
        "word_counts": {
            "generated": generated_words,
            "human": human_words,
            "source": source_words,
            "generated_vs_human_ratio": round(generated_words / human_words, 4) if human_words else None,
        },
        "headings": {
            "generated_count": len(generated_headings),
            "human_count": len(human_headings),
            **heading_audit,
        },
        "source_facts": fact_audit,
        "common_topics": topic_audit,
        "organization_patterns": dump_model(organization_audit),
        "issues": issues,
        "recommendations": recommendations,
    }


def extract_headings(text: str) -> list[str]:
    headings: list[str] = []
    seen: set[str] = set()
    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if not line or len(line) > 120:
            continue
        title = ""
        markdown_match = MARKDOWN_HEADING_RE.match(line)
        if markdown_match:
            title = markdown_match.group("title")
        else:
            numbered_match = NUMBERED_HEADING_RE.match(line)
            if numbered_match:
                title = numbered_match.group("title") or line
        title = _clean_heading(title)
        key = _normalize_title(title)
        if title and key and key not in seen:
            seen.add(key)
            headings.append(title)
    return headings


def extract_high_value_facts(text: str, *, limit: int = 120) -> list[dict[str, str]]:
    facts: list[dict[str, str]] = []
    seen: set[str] = set()
    for line_no, raw_line in enumerate((text or "").splitlines(), start=1):
        line = " ".join(raw_line.split())
        if not line or len(line) < 6:
            continue
        for match in FACT_RE.finditer(line):
            value = match.group("value").strip()
            key = _normalize_fact(value)
            if key in seen:
                continue
            seen.add(key)
            facts.append(
                {
                    "fact": value,
                    "line": str(line_no),
                    "context": _trim(line, 180),
                    "kind": _fact_kind(line),
                }
            )
            if len(facts) >= limit:
                return facts
        for match in STANDARD_RE.finditer(line):
            value = match.group(0).strip()
            key = _normalize_fact(value)
            if key in seen:
                continue
            seen.add(key)
            facts.append(
                {
                    "fact": value,
                    "line": str(line_no),
                    "context": _trim(line, 180),
                    "kind": "standard",
                }
            )
            if len(facts) >= limit:
                return facts
    return facts


def audit_fact_absorption(generated: str, facts: list[dict[str, str]]) -> dict[str, Any]:
    normalized_generated = _normalize_fact(generated)
    absorbed: list[dict[str, str]] = []
    omitted: list[dict[str, str]] = []
    for fact in facts:
        token = _normalize_fact(fact["fact"])
        if token and token in normalized_generated:
            absorbed.append(fact)
        else:
            omitted.append(fact)
    return {
        "candidate_count": len(facts),
        "absorbed_count": len(absorbed),
        "omitted_count": len(omitted),
        "absorption_ratio": round(len(absorbed) / len(facts), 4) if facts else None,
        "omitted_examples": omitted[:20],
    }


def audit_common_topics(generated: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, terms in COMMON_TOPIC_TERMS.items():
        hits = [term for term in terms if term in generated]
        result[key] = {
            "covered": bool(hits),
            "hits": hits,
            "missing_terms": [term for term in terms if term not in hits],
        }
    return result


def audit_heading_overlap(generated_headings: list[str], human_headings: list[str]) -> dict[str, Any]:
    if not human_headings:
        return {
            "matched_human_heading_count": 0,
            "human_heading_coverage_ratio": None,
            "missing_human_heading_examples": [],
        }
    generated_keys = {_normalize_title(title) for title in generated_headings}
    matched = []
    missing = []
    for heading in human_headings:
        key = _normalize_title(heading)
        if not key:
            continue
        if key in generated_keys or any(key in item or item in key for item in generated_keys if len(item) >= 4):
            matched.append(heading)
        else:
            missing.append(heading)
    return {
        "matched_human_heading_count": len(matched),
        "human_heading_coverage_ratio": round(len(matched) / max(1, len(matched) + len(missing)), 4),
        "missing_human_heading_examples": missing[:30],
    }


def render_quality_audit_markdown(report: dict[str, Any]) -> str:
    lines = [
        f"# Generation Quality Audit: {report['project_key']}",
        "",
        "## Summary",
        f"- generated words: {report['word_counts']['generated']}",
        f"- human words: {report['word_counts']['human'] or '-'}",
        f"- generated/human ratio: {report['word_counts']['generated_vs_human_ratio']}",
        f"- generated headings: {report['headings']['generated_count']}",
        f"- human headings: {report['headings']['human_count']}",
        f"- human heading coverage: {report['headings']['human_heading_coverage_ratio']}",
        f"- source fact absorption: {report['source_facts']['absorption_ratio']}",
        f"- organization coverage: {report.get('organization_patterns', {}).get('average_coverage_ratio')}",
        "",
        "## Issues",
    ]
    if report["issues"]:
        lines.extend(f"- {item}" for item in report["issues"])
    else:
        lines.append("- No major heuristic issue detected.")
    lines.extend(["", "## Recommendations"])
    if report.get("recommendations"):
        for item in report["recommendations"]:
            lines.extend(
                [
                    f"### {item['action']}",
                    f"- severity: {item['severity']}",
                    f"- reason: {item['reason']}",
                    "- next_steps:",
                    *[f"  - {step}" for step in item["next_steps"]],
                    "",
                ]
            )
    else:
        lines.append("- No automated control recommendation.")
    lines.extend(["", "## Topic Coverage"])
    for key, item in report["common_topics"].items():
        status = "PASS" if item["covered"] else "MISS"
        hits = "；".join(item["hits"]) if item["hits"] else "-"
        lines.append(f"- {key}: {status}; hits={hits}")
    lines.extend(["", "## Organization Pattern Coverage"])
    organization = report.get("organization_patterns", {})
    audits = organization.get("audits", [])
    if audits:
        for item in audits:
            if not item.get("applicable"):
                continue
            lines.extend(
                [
                    f"### {item['pattern_key']}",
                    f"- coverage_ratio: {item.get('coverage_ratio')}",
                    f"- suggested_action: {item.get('suggested_action')}",
                    "- covered_points: " + ("；".join(item.get("covered_points") or []) or "-"),
                    "- missing_points: " + ("；".join(item.get("missing_points") or []) or "-"),
                    "",
                ]
            )
    else:
        lines.append("- No organization pattern audit available.")
    lines.extend(["", "## Omitted Source Fact Examples"])
    omitted = report["source_facts"]["omitted_examples"]
    if omitted:
        for item in omitted:
            lines.append(f"- `{item['fact']}` ({item['kind']}, L{item['line']}): {item['context']}")
    else:
        lines.append("- None.")
    lines.extend(["", "## Missing Human Heading Examples"])
    missing = report["headings"]["missing_human_heading_examples"]
    if missing:
        lines.extend(f"- {item}" for item in missing)
    else:
        lines.append("- None.")
    return "\n".join(lines).strip() + "\n"


def _quality_issues(
    *,
    generated_words: int,
    human_words: int,
    heading_audit: dict[str, Any],
    fact_audit: dict[str, Any],
    topic_audit: dict[str, Any],
    organization_audit: dict[str, Any] | None = None,
) -> list[str]:
    issues: list[str] = []
    if human_words and generated_words < human_words * 0.35:
        issues.append("Generated document is far shorter than the human reference; detail budget or subsection expansion is likely insufficient.")
    heading_ratio = heading_audit.get("human_heading_coverage_ratio")
    if heading_ratio is not None and heading_ratio < 0.35:
        issues.append("Generated heading tree covers too few human-reference topics; outline coverage or source-derived subsection proposal needs improvement.")
    fact_ratio = fact_audit.get("absorption_ratio")
    if fact_ratio is not None and fact_audit.get("candidate_count", 0) >= 10 and fact_ratio < 0.25:
        issues.append("Many high-value numeric or standard facts from the source are not present in the generated body; evidence utilization should trigger regeneration.")
    missing_topics = [key for key, item in topic_audit.items() if not item["covered"]]
    if len(missing_topics) >= 3:
        issues.append("Several common construction-organization topics are missing: " + ", ".join(missing_topics))
    organization_ratio = (organization_audit or {}).get("average_coverage_ratio")
    applicable_count = (organization_audit or {}).get("applicable_pattern_count") or 0
    if organization_ratio is not None and applicable_count and organization_ratio < 0.5:
        issues.append(
            "Generated content does not cover enough reusable construction-plan organization points; pattern-guided outline/detail repair is needed."
        )
    return issues


def _quality_recommendations(
    *,
    generated_words: int,
    human_words: int,
    heading_audit: dict[str, Any],
    fact_audit: dict[str, Any],
    topic_audit: dict[str, Any],
    organization_audit: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    recommendations: list[dict[str, Any]] = []
    word_ratio = round(generated_words / human_words, 4) if human_words else None
    heading_ratio = heading_audit.get("human_heading_coverage_ratio")
    fact_ratio = fact_audit.get("absorption_ratio")
    missing_topics = [key for key, item in topic_audit.items() if not item["covered"]]
    organization_ratio = (organization_audit or {}).get("average_coverage_ratio")
    organization_issues = (organization_audit or {}).get("issues") or []

    if word_ratio is not None and word_ratio < 0.35:
        recommendations.append(
            {
                "action": "increase_detail_budget",
                "severity": "warning",
                "reason": f"Generated/human word ratio is {word_ratio}, below the 0.35 detail threshold.",
                "next_steps": [
                    "Re-estimate outline target word counts from the human reference.",
                    "Increase target_word_count for sparse chapters before regeneration.",
                    "For craft chapters, prefer subsection expansion over one large prompt.",
                ],
            }
        )
    if heading_ratio is not None and heading_ratio < 0.35:
        recommendations.append(
            {
                "action": "repair_outline_coverage",
                "severity": "warning",
                "reason": f"Human heading coverage is {heading_ratio}, below the 0.35 coverage threshold.",
                "next_steps": [
                    "Run the outline coverage proposal before full regeneration.",
                    "Create project outline nodes for missing high-value source or human-reference topics.",
                    "Use source-derived subsection proposals for dense craft chapters.",
                ],
            }
        )
    if fact_ratio is not None and fact_audit.get("candidate_count", 0) >= 10 and fact_ratio < 0.25:
        recommendations.append(
            {
                "action": "strengthen_evidence_utilization",
                "severity": "warning",
                "reason": f"Source fact absorption is {fact_ratio}; many numeric, parameter, or standard facts are omitted.",
                "next_steps": [
                    "Inspect omitted_examples and confirm whether they belong to generated chapters.",
                    "Ensure required_source_facts are included in chapter prompts.",
                    "Trigger regenerate with revision context for chapters that omit mapped high-value facts.",
                ],
            }
        )
    if len(missing_topics) >= 3:
        recommendations.append(
            {
                "action": "add_missing_common_topics",
                "severity": "warning",
                "reason": "Generated document misses common construction-organization topics: " + ", ".join(missing_topics),
                "next_steps": [
                    "Create outline proposals for missing common topics.",
                    "Keep unsupported topics as human-input placeholders instead of unsupported factual text.",
                ],
            }
        )
    if organization_ratio is not None and organization_ratio < 0.5:
        recommendations.append(
            {
                "action": "repair_outline_coverage",
                "severity": "warning",
                "reason": f"Reusable organization pattern coverage is {organization_ratio}; generated text is not yet organized like a complete construction plan.",
                "next_steps": [
                    "Use writing pattern cards to add missing expected points to outline nodes or subchapters.",
                    "For craft chapters, split source-backed subtopics before regeneration.",
                    "Regenerate chapters whose evidence exists but whose expected organization points are missing.",
                    *organization_issues[:4],
                ],
            }
        )
    return recommendations


def _clean_heading(title: str) -> str:
    title = re.sub(r"\s+", " ", title or "").strip(" #\t\r\n")
    title = re.sub(r"^[一二三四五六七八九十]+[、.．]\s*", "", title)
    title = re.sub(r"^\d+(?:\.\d+){0,5}[、.．]?\s*", "", title)
    return title.strip()


def _normalize_title(title: str) -> str:
    return re.sub(r"[\s#：:、，,。.．（）()《》\-—_/]+", "", title or "").lower()


def _normalize_fact(text: str) -> str:
    return re.sub(r"\s+", "", text or "").replace("～", "-").replace("至", "-").lower()


def _fact_kind(line: str) -> str:
    if any(term in line for term in ("压力", "流量", "孔深", "孔径", "配比", "压实", "温度", "厚度", "间距")):
        return "parameter"
    if any(term in line for term in ("工程量", "数量", "开挖", "填筑", "钻孔", "灌浆", "注水", "覆盖")):
        return "quantity"
    if any(term in line for term in ("工期", "开工", "完工", "竣工", "计划")):
        return "schedule"
    return "numeric"


def _trim(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."
