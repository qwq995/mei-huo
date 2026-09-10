from __future__ import annotations

import html
import re
from dataclasses import dataclass

from coalplan.application.reference_atom_v2 import finalize_v2_atom
from coalplan.domain.reference_library import ReferenceAtom, ReferenceReviewStatus


HTML_ENTITY_RE = re.compile(r"&(?:#x?[0-9A-Fa-f]+|[A-Za-z][A-Za-z0-9]+);")
OCR_NOISE_RE = re.compile(r"[�]|(?:Ã|Â|â€™|â€œ|â€|ï¿½)|[\uFFF0-\uFFFF]")
BAD_TITLE_RE = re.compile(r"(?:�|Ã|Â|â|ï¿½|[\u0000-\u001f])")
SLOT_RE = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")
HISTORICAL_RE = re.compile(r"(?:历史项目|原项目|上一个项目|上一工程|截至\s*20\d{2}年|已建成多年)")


@dataclass(frozen=True)
class AtomAudit:
    atom_id: str
    blockers: list[str]
    warnings: list[str]
    safe_changes: list[str]
    allowed: bool


def _clean(value: str) -> tuple[str, list[str]]:
    changes: list[str] = []
    decoded = html.unescape(value or "")
    if decoded != value:
        changes.append("解码 HTML 实体字符")
    decoded = decoded.replace("\u200b", "").replace("\ufeff", "")
    decoded = re.sub(r"[ \t]+", " ", decoded)
    return decoded.strip(), changes


def _has_structured_overlap(item: str, text: str) -> bool:
    words = re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z0-9]{3,}", item)
    if not words:
        return True
    return sum(1 for word in words if word in text) >= max(1, min(2, len(words)))


def audit_atom(atom: ReferenceAtom, *, quality_threshold: float = 0.94) -> tuple[ReferenceAtom, AtomAudit]:
    original_template_slots = set(SLOT_RE.findall(atom.parameterized_template or ""))
    original_declared_slots = {slot.slot_key for slot in atom.parameter_slots if slot.slot_key}
    had_template_mismatch = original_template_slots != original_declared_slots
    original_content = atom.content
    original_path = list(atom.title_path)
    atom.content, content_changes = _clean(atom.content)
    atom.raw_excerpt, raw_changes = _clean(atom.raw_excerpt or atom.content)
    atom.normalized_text, normalized_changes = _clean(atom.normalized_text or atom.content)
    atom.title_path = [_clean(item)[0] for item in atom.title_path if _clean(item)[0]]
    safe_changes = content_changes + raw_changes + normalized_changes
    if atom.content != original_content:
        safe_changes.append("清理正文中的不可见字符或实体字符")
    if atom.title_path != original_path:
        safe_changes.append("清理标题路径中的异常字符")

    # Rebuild slots and the parameterized template after safe normalization.
    finalize_v2_atom(atom)
    blockers = list(dict.fromkeys(atom.publication_blockers))
    warnings: list[str] = []
    text = "\n".join((atom.raw_excerpt, atom.normalized_text, atom.content))

    if HTML_ENTITY_RE.search(atom.content) or HTML_ENTITY_RE.search(atom.title_path[-1] if atom.title_path else ""):
        blockers.append("正文或标题路径仍含未处理的 HTML 实体")
    if OCR_NOISE_RE.search(text) or any(OCR_NOISE_RE.search(item) for item in atom.title_path):
        blockers.append("疑似 OCR 乱码或编码损坏")
    if any(BAD_TITLE_RE.search(item) for item in atom.title_path):
        blockers.append("标题路径含乱码或控制字符")

    template_slots = set(SLOT_RE.findall(atom.parameterized_template or ""))
    declared_slots = {slot.slot_key for slot in atom.parameter_slots if slot.slot_key}
    if had_template_mismatch or template_slots != declared_slots:
        blockers.append("模板槽位集合与参数槽定义不一致")
    if any(slot.source_value and slot.source_value not in atom.raw_excerpt for slot in atom.parameter_slots):
        blockers.append("参数槽来源值不在原始引文中")

    structured = [
        *atom.action_sequence,
        *atom.control_points,
        *atom.acceptance_checks,
        *atom.exceptions,
        *atom.risks,
    ]
    unsupported = [item for item in structured if not _has_structured_overlap(item, atom.raw_excerpt)]
    if unsupported:
        blockers.append("结构化字段存在原文无法支撑的内容")
        warnings.append("结构化字段待人工核对：" + "；".join(unsupported[:3]))

    if HISTORICAL_RE.search(atom.content):
        blockers.append("正文残留历史项目或历史事实表述")
    if atom.quality_score < quality_threshold:
        blockers.append(f"质量分低于 {quality_threshold:.2f}")

    if atom.atom_type in {"process", "control", "inspection", "exception"} and not atom.acceptance_checks:
        blockers.append("缺少验收或检查字段")
    if atom.atom_type in {"process", "control", "exception"} and not atom.risks:
        blockers.append("缺少风险字段")
    if atom.atom_type in {"process", "control", "inspection"} and not atom.parameter_slots:
        blockers.append("缺少参数槽")
    if not atom.engineering_system:
        blockers.append("缺少工程系统标签")
    if len(atom.content.strip()) < 40:
        warnings.append("引文过短，建议与相邻完整工序合并或退回")

    atom.publication_blockers = list(dict.fromkeys(blockers))
    atom.migration_warning = list(dict.fromkeys([*atom.migration_warning, *warnings]))
    if atom.publication_blockers and atom.status == ReferenceReviewStatus.published:
        atom.status = ReferenceReviewStatus.ai_candidate
    return atom, AtomAudit(atom.id, atom.publication_blockers, warnings, safe_changes, not atom.publication_blockers)


def audit_atoms(atoms: list[ReferenceAtom], *, apply: bool = False, quality_threshold: float = 0.94) -> dict:
    results: list[AtomAudit] = []
    audited: list[ReferenceAtom] = []
    for atom in atoms:
        audited_atom, result = audit_atom(atom, quality_threshold=quality_threshold)
        audited.append(audited_atom)
        results.append(result)
    return {
        "atom_count": len(results),
        "clean_count": sum(item.allowed for item in results),
        "blocked_count": sum(not item.allowed for item in results),
        "safe_change_count": sum(bool(item.safe_changes) for item in results),
        "applied": apply,
        "results": [item.__dict__ for item in results],
        "atoms": audited,
    }
