from __future__ import annotations

import re
from dataclasses import dataclass

from coalplan.domain.reference_library import AtomParameterSlot, ReferenceAtom, ReferenceReviewStatus


SPECIFIC_TOKEN_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])(?:K\d+\+\d+|\d+(?:\.\d+)?(?:\s*[~～—-]\s*\d+(?:\.\d+)?)?\s*"
    r"(?:MPa|kPa|kW|MW|kV|mm|cm|km|m²|m2|m³|m3|min|kg|Pa|m|V|A|h|d|天|月|年|%|℃|°|台|套|人|次|孔|根|t|L|s))",
    re.I,
)
STANDARD_PATTERN = re.compile(r"(?:GB|GB/T|DL/T|NB/T|SL|JGJ|JTG|DB\d*/T)[\s-]*\d+(?:\.\d+)?(?:-\d{4})?", re.I)
PROJECT_ENTITY_PATTERN = re.compile(r"[\u4e00-\u9fffA-Za-z0-9·（）()]{1,40}(?:抽水蓄能电站|水电站|项目部|有限公司|工程局|标段)")


@dataclass(frozen=True)
class PublicationGate:
    allowed: bool
    coverage: float
    blockers: list[str]
    risky_tokens: list[str]


def normalize_reference_text(text: str) -> str:
    lines: list[str] = []
    previous = ""
    for raw in text.replace("\r\n", "\n").splitlines():
        line = raw.strip()
        if not line:
            if lines and lines[-1]:
                lines.append("")
            continue
        if line == previous:
            continue
        if re.fullmatch(r"(?:第?\s*\d+\s*页(?:\s*共\s*\d+\s*页)?|[-—_ ]{3,})", line):
            continue
        lines.append(line)
        previous = line
    return "\n".join(lines).strip()


def detect_specific_tokens(text: str) -> list[tuple[str, int, int, str]]:
    found: list[tuple[str, int, int, str]] = []
    for pattern, role in (
        (SPECIFIC_TOKEN_PATTERN, "project_specific"),
        (STANDARD_PATTERN, "normative_reference"),
        (PROJECT_ENTITY_PATTERN, "project_entity"),
    ):
        for match in pattern.finditer(text):
            token = match.group(0).strip()
            if token and not any(start == match.start() and end == match.end() for _, start, end, _ in found):
                found.append((token, match.start(), match.end(), role))
    return sorted(found, key=lambda item: (item[1], item[2]))


def build_parameter_slots(text: str, ai_slots: list[AtomParameterSlot] | None = None) -> list[AtomParameterSlot]:
    slots = _deduplicate_ai_slots(text, list(ai_slots or []))
    covered_values = [slot.source_value for slot in slots if slot.source_value]
    counters: dict[str, int] = {}
    for value, start, end, role in detect_specific_tokens(text):
        if any(value in covered or covered in value for covered in covered_values):
            continue
        counters[role] = counters.get(role, 0) + 1
        slot_key = f"{role}.{counters[role]}"
        unit_match = re.search(r"[A-Za-z²³℃°%]+|[台套人次孔根天月年]$", value)
        slots.append(
            AtomParameterSlot(
                slot_key=slot_key,
                display_name=value,
                source_value=value,
                unit=unit_match.group(0) if unit_match else "",
                data_type="number_with_unit" if role == "project_specific" else "text",
                semantic_role=role,
                reuse_policy="keep_normative_with_version_check" if role == "normative_reference" else "replace_from_evidence",
                source_start=start,
                source_end=end,
            )
        )
        covered_values.append(value)
    return slots


def _deduplicate_ai_slots(text: str, slots: list[AtomParameterSlot]) -> list[AtomParameterSlot]:
    kept: list[AtomParameterSlot] = []
    used_keys: set[str] = set()
    for slot in sorted(slots, key=lambda item: len(item.source_value or ""), reverse=True):
        value = slot.source_value.strip()
        if not value or value not in text:
            continue
        if any(value in item.source_value or item.source_value in value for item in kept):
            continue
        base_key = slot.slot_key.strip() or "project_specific"
        key = base_key
        suffix = 2
        while key in used_keys:
            key = f"{base_key}.{suffix}"
            suffix += 1
        slot.slot_key = key
        used_keys.add(key)
        if slot.semantic_role != "normative_reference" or not STANDARD_PATTERN.fullmatch(value):
            slot.reuse_policy = "replace_from_evidence"
        kept.append(slot)
    return kept


def parameterize_text(text: str, slots: list[AtomParameterSlot]) -> str:
    result = text
    indexed = sorted(
        [slot for slot in slots if slot.source_value],
        key=lambda slot: len(slot.source_value),
        reverse=True,
    )
    for slot in indexed:
        result = result.replace(slot.source_value, "{{" + slot.slot_key + "}}")
    return result


def evaluate_publication_gate(atom: ReferenceAtom) -> PublicationGate:
    text = atom.raw_excerpt or atom.content
    risky = [item[0] for item in detect_specific_tokens(text)]
    covered = [slot.source_value for slot in atom.parameter_slots if slot.source_value]
    missing = [
        token for token in risky
        if not any(token in value or value in token for value in covered)
    ]
    coverage = 1.0 if not risky else (len(risky) - len(missing)) / len(risky)
    blockers: list[str] = []
    if atom.schema_version != "v2":
        blockers.append("原子尚未升级到 V2 数据契约")
    minimum_chars = _minimum_content_chars(atom)
    if len((atom.normalized_text or atom.content).strip()) < minimum_chars:
        blockers.append(f"正文不足 {minimum_chars} 字，且结构化控制信息不足")
    if not atom.chapter_module:
        blockers.append("缺少文档模块标签")
    if not atom.engineering_object and not atom.engineering_system:
        blockers.append("缺少工程对象或工程系统标签")
    if not atom.process_family and atom.atom_type in {"process", "control", "inspection", "exception"}:
        blockers.append("技术原子缺少工艺族标签")
    if missing:
        blockers.append("存在未参数化的项目实体、标准或数值：" + "、".join(missing[:8]))
    return PublicationGate(not blockers, coverage, blockers, risky)


def _minimum_content_chars(atom: ReferenceAtom) -> int:
    structured_points = sum(
        len(items)
        for items in (
            atom.action_sequence,
            atom.control_points,
            atom.acceptance_checks,
            atom.exceptions,
            atom.prohibited_scenarios,
        )
    )
    if atom.atom_type in {"control", "inspection"} and structured_points >= 2:
        return 20
    if atom.atom_type == "process" and len(atom.action_sequence) >= 2:
        return 30
    if atom.atom_type == "exception" and atom.exceptions and atom.action_sequence:
        return 30
    return 80


def finalize_v2_atom(atom: ReferenceAtom) -> ReferenceAtom:
    atom.schema_version = "v2"
    atom.raw_excerpt = atom.raw_excerpt or atom.content
    atom.normalized_text = normalize_reference_text(atom.normalized_text or atom.content)
    atom.parameter_slots = build_parameter_slots(atom.raw_excerpt, atom.parameter_slots)
    for slot in atom.parameter_slots:
        if slot.source_start is None and slot.source_value:
            position = atom.raw_excerpt.find(slot.source_value)
            if position >= 0:
                slot.source_start = position
                slot.source_end = position + len(slot.source_value)
    atom.parameterized_template = parameterize_text(atom.normalized_text, atom.parameter_slots)
    gate = evaluate_publication_gate(atom)
    atom.parameter_coverage = gate.coverage
    atom.publication_blockers = gate.blockers
    if atom.status == ReferenceReviewStatus.published and not gate.allowed:
        atom.status = ReferenceReviewStatus.ai_candidate
    return atom
