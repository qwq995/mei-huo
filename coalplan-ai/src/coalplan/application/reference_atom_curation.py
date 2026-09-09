from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from coalplan.domain.reference_library import AtomRelation, ReferenceAtom


@dataclass
class AtomConflict:
    left_atom_id: str
    right_atom_id: str
    parameter_name: str
    left_value: str
    right_value: str
    reason: str


@dataclass
class AtomCurationResult:
    atoms: list[ReferenceAtom]
    duplicate_groups: dict[str, list[str]] = field(default_factory=dict)
    conflicts: list[AtomConflict] = field(default_factory=list)


def curate_reference_atoms(atoms: list[ReferenceAtom], *, duplicate_threshold: float = 0.9) -> AtomCurationResult:
    """Relate duplicates and parameter variants without silently merging source records."""
    groups: dict[str, list[str]] = {}
    conflicts: list[AtomConflict] = []
    compared: set[tuple[str, str]] = set()
    buckets: dict[tuple[str, str, str], list[ReferenceAtom]] = defaultdict(list)
    for atom in atoms:
        buckets[(atom.chapter_module, atom.engineering_system, atom.process_family)].append(atom)
    atom_by_id = {atom.id: atom for atom in atoms}
    for bucket in buckets.values():
        ordered = sorted(bucket, key=lambda atom: atom.id)
        for index, left in enumerate(ordered):
            for right in ordered[index + 1:]:
                if not _same_scope(left, right):
                    continue
                pair = tuple(sorted((left.id, right.id)))
                if pair in compared:
                    continue
                compared.add(pair)
                similarity = _text_similarity(left, right)
                if similarity >= duplicate_threshold:
                    group_id = _group_id(left, right)
                    members = groups.setdefault(group_id, [])
                    for atom_id in (left.id, right.id):
                        if atom_id not in members:
                            members.append(atom_id)
                    _relate(left, right, "duplicate_of", f"参数化正文相似度 {similarity:.3f}")
                conflicts.extend(_parameter_conflicts(left, right))
    for conflict in conflicts:
        left = atom_by_id[conflict.left_atom_id]
        right = atom_by_id[conflict.right_atom_id]
        _relate(left, right, "conflicts_with", conflict.reason)
    return AtomCurationResult(atoms, groups, conflicts)


def _same_scope(left: ReferenceAtom, right: ReferenceAtom) -> bool:
    if left.id == right.id:
        return False
    if left.chapter_module and right.chapter_module and left.chapter_module != right.chapter_module:
        return False
    if left.engineering_system and right.engineering_system and left.engineering_system != right.engineering_system:
        return False
    return _tag_similarity(left.process_family, right.process_family) >= 0.45


def _text_similarity(left: ReferenceAtom, right: ReferenceAtom) -> float:
    left_text = _normalized_template(left)
    right_text = _normalized_template(right)
    if not left_text or not right_text:
        return 0.0
    return SequenceMatcher(None, left_text, right_text).ratio()


def _normalized_template(atom: ReferenceAtom) -> str:
    text = atom.parameterized_template or atom.normalized_text or atom.content
    text = re.sub(r"\{\{[^}]+\}\}", "<参数>", text)
    return re.sub(r"[^a-z0-9\u4e00-\u9fff<>]", "", text.lower())


def _parameter_conflicts(left: ReferenceAtom, right: ReferenceAtom) -> list[AtomConflict]:
    conflicts: list[AtomConflict] = []
    for left_slot in left.parameter_slots:
        for right_slot in right.parameter_slots:
            if not _comparable_parameter_slots(left, right, left_slot.slot_key, right_slot.slot_key):
                continue
            if _equivalent_parameter_values(left_slot.source_value, right_slot.source_value):
                continue
            conflicts.append(AtomConflict(
                left_atom_id=left.id,
                right_atom_id=right.id,
                parameter_name=left_slot.display_name or right_slot.display_name,
                left_value=left_slot.source_value,
                right_value=right_slot.source_value,
                reason=(
                    f"同类工艺参数“{left_slot.display_name or right_slot.display_name}”存在历史取值差异："
                    f"{left_slot.source_value} / {right_slot.source_value}；应按当前项目证据或试验确定"
                ),
            ))
    return conflicts


def _comparable_parameter_slots(
    left: ReferenceAtom,
    right: ReferenceAtom,
    left_key: str,
    right_key: str,
) -> bool:
    if not left_key or left_key != right_key:
        return False
    if left_key.startswith(("project_specific.", "project_entity.", "normative_reference.")):
        return False
    left_object = _normalized_label(left.engineering_object)
    right_object = _normalized_label(right.engineering_object)
    return not (left_object and right_object and left_object != right_object)


def _equivalent_parameter_values(left: str, right: str) -> bool:
    left_normalized = _normalized_label(left)
    right_normalized = _normalized_label(right)
    if left_normalized == right_normalized:
        return True
    if min(len(left_normalized), len(right_normalized)) >= 4 and (
        left_normalized in right_normalized or right_normalized in left_normalized
    ):
        return True
    left_numbers = _numeric_signature(left)
    right_numbers = _numeric_signature(right)
    if bool(left_numbers) != bool(right_numbers):
        return True
    return bool(left_numbers and right_numbers and left_numbers == right_numbers)


def _numeric_signature(value: str) -> tuple[str, ...]:
    normalized = value.translate(str.maketrans({"—": "-", "–": "-", "～": "-", "~": "-"}))
    return tuple(re.findall(r"\d+(?:\.\d+)?", normalized))


def _normalized_label(value: str) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]", "", (value or "").lower())


def _tag_similarity(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    left_terms = _bigrams(left)
    right_terms = _bigrams(right)
    return len(left_terms & right_terms) / max(1, min(len(left_terms), len(right_terms)))


def _bigrams(text: str) -> set[str]:
    compact = re.sub(r"\s+", "", text.lower())
    if len(compact) < 2:
        return {compact} if compact else set()
    return {compact[index:index + 2] for index in range(len(compact) - 1)}


def _group_id(left: ReferenceAtom, right: ReferenceAtom) -> str:
    import hashlib

    seed = ":".join(sorted((left.id, right.id)))
    return "dup_" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]


def _relate(left: ReferenceAtom, right: ReferenceAtom, relation_type: str, reason: str) -> None:
    if not any(item.relation_type == relation_type and item.target_atom_id == right.id for item in left.relations):
        left.relations.append(AtomRelation(relation_type=relation_type, target_atom_id=right.id, reason=reason))
    if not any(item.relation_type == relation_type and item.target_atom_id == left.id for item in right.relations):
        right.relations.append(AtomRelation(relation_type=relation_type, target_atom_id=left.id, reason=reason))
