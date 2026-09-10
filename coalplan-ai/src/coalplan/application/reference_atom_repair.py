from __future__ import annotations

import re
from dataclasses import dataclass

from coalplan.application.reference_atom_audit import audit_atom, _has_structured_overlap
from coalplan.application.reference_atom_v2 import finalize_v2_atom
from coalplan.domain.reference_library import ReferenceAtom


SYSTEM_RULES = (
    ("灌浆", "灌浆系统"), ("混凝土|浇筑|振捣", "混凝土施工系统"),
    ("隧洞|隧道|洞身|洞挖", "地下洞室系统"), ("钻孔|爆破|炮孔", "钻爆开挖系统"),
    ("锚杆|喷混凝土|支护", "支护系统"), ("边坡|锚索|排水孔", "边坡支护系统"),
    ("钢筋|模板", "混凝土施工系统"), ("金属结构|闸门|启闭机", "金属结构安装系统"),
    ("施工道路|交通|供水|供电|供风", "临建设施系统"),
)
MODULE_RULES = (
    ("质量|检验|验收|试验", "质量验收"), ("安全|风险|应急|事故", "安全管理"),
    ("环保|水保|文明施工", "环保水保"), ("进度|工期|计划", "进度资源"),
    ("部署|组织机构|总平面|临建", "施工部署"),
)
SENTENCE_RE = re.compile(r"[^。！？；\n]{4,120}[。！？；]?")


@dataclass(frozen=True)
class RepairOutcome:
    atom_id: str
    repaired: list[str]
    unresolved: list[str]
    publishable: bool


def _source_sentences(text: str, pattern: str) -> list[str]:
    return [sentence.strip() for sentence in SENTENCE_RE.findall(text or "") if re.search(pattern, sentence)]


def repair_atom(atom: ReferenceAtom, *, quality_threshold: float = 0.94) -> tuple[ReferenceAtom, RepairOutcome]:
    repaired: list[str] = []
    unresolved: list[str] = []
    source = atom.raw_excerpt or atom.content

    if not re.search(r"[�]|(?:Ã|Â|â€™|â€œ|â€|ï¿½)", source):
        if not atom.engineering_system:
            for pattern, label in SYSTEM_RULES:
                if re.search(pattern, source + " " + "/".join(atom.title_path)):
                    atom.engineering_system = label
                    repaired.append("补齐工程系统标签")
                    break
        if not atom.chapter_module:
            for pattern, label in MODULE_RULES:
                if re.search(pattern, source + " " + "/".join(atom.title_path)):
                    atom.chapter_module = label
                    repaired.append("补齐章节模块标签")
                    break

        if atom.atom_type in {"process", "control", "exception"} and not atom.risks:
            risks = _source_sentences(source, r"风险|危险|坍塌|失稳|漏浆|堵管|盲炮|涌水|触电|高处|机械伤害")
            if risks:
                atom.risks = risks[:3]
                repaired.append("从原文恢复风险字段")
        if atom.atom_type in {"process", "control", "inspection", "exception"} and not atom.acceptance_checks:
            checks = _source_sentences(source, r"检查|验收|检测|检验|记录|符合|合格")
            if checks:
                atom.acceptance_checks = checks[:3]
                repaired.append("从原文恢复验收/检查字段")

        # Remove only structured claims that cannot be traced to this excerpt;
        # the original prose remains untouched and can still be re-reviewed.
        for field in ("action_sequence", "control_points", "acceptance_checks", "exceptions", "risks"):
            values = getattr(atom, field)
            kept = [item for item in values if _has_structured_overlap(item, source)]
            if len(kept) != len(values):
                setattr(atom, field, kept)
                repaired.append(f"移除{field}中无法回溯原文的条目")

        before = atom.parameterized_template
        finalize_v2_atom(atom)
        if atom.parameterized_template != before:
            repaired.append("重建参数槽与参数化模板")
    else:
        unresolved.append("原始引文存在编码/OCR 损坏，不能凭空恢复")

    audited, audit = audit_atom(atom, quality_threshold=quality_threshold)
    unresolved.extend(audit.blockers)
    unresolved = list(dict.fromkeys(unresolved))
    return audited, RepairOutcome(atom.id, list(dict.fromkeys(repaired)), unresolved, audit.allowed)


def repair_atoms(atoms: list[ReferenceAtom], *, quality_threshold: float = 0.94) -> dict:
    repaired_atoms: list[ReferenceAtom] = []
    outcomes: list[RepairOutcome] = []
    for atom in atoms:
        fixed, outcome = repair_atom(atom, quality_threshold=quality_threshold)
        repaired_atoms.append(fixed)
        outcomes.append(outcome)
    return {
        "atom_count": len(outcomes),
        "publishable_count": sum(item.publishable for item in outcomes),
        "repaired_count": sum(bool(item.repaired) for item in outcomes),
        "unresolved_count": sum(bool(item.unresolved) for item in outcomes),
        "outcomes": [item.__dict__ for item in outcomes],
        "atoms": repaired_atoms,
    }
