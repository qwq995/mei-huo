from __future__ import annotations

import csv
import hashlib
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path

from coalplan.domain.documents import stable_id
from coalplan.domain.reference_library import (
    KnowledgeRole,
    ReferenceCorpusCatalog,
    ReferenceDocumentEntry,
    ReferenceDocumentKind,
)


_PROJECT_TYPES = {
    "1.宁夏煤火": "煤火治理",
    "2.扎拉项目部": "水电/导流隧洞/边坡",
    "3.柯拉二期光伏发电项目": "光伏",
    "4.扎拉山光伏": "光伏",
    "5.明阳风电": "风电",
    "6.巴塘项目部": "水电/地下洞室",
    "7.叶巴滩": "水电",
    "8.昌波首部枢纽": "水电/首部枢纽",
    "9.泰顺项目": "抽水蓄能",
    "10.拉哇项目部": "水电/泄洪洞",
    "11.两河口项目部": "水电/道路隧洞",
    "12.锦屏道路": "水电/道路养护",
    "13.西三中": "水环境/市政",
    "安化": "抽水蓄能",
    "德令哈光伏项目": "光伏",
    "贵州织金项目": "工业场平/土石方",
    "科学城": "市政/水环境",
    "龙溪河": "水环境/河道治理",
    "马关光伏": "光伏",
    "桐城c1": "抽水蓄能",
    "桐城q1": "抽水蓄能",
    "旭龙": "水电/大坝",
    "中卫风电": "风电",
}


def build_reference_corpus_catalog(source_root: Path) -> ReferenceCorpusCatalog:
    root = source_root.resolve()
    if not root.exists():
        raise FileNotFoundError(f"Reference corpus directory does not exist: {root}")

    entries: list[ReferenceDocumentEntry] = []
    first_by_hash: dict[str, ReferenceDocumentEntry] = {}
    for path in sorted(root.rglob("*.md"), key=lambda item: str(item).lower()):
        entry = _catalog_one(root, path)
        duplicate = first_by_hash.get(entry.content_hash)
        if duplicate is not None:
            entry.exact_duplicate_of = duplicate.document_id
            entry.atom_candidate = False
            entry.quality_tier = "D"
            entry.exclusion_reasons.append("与已收录文档内容完全重复")
        else:
            first_by_hash[entry.content_hash] = entry
        entries.append(entry)

    return ReferenceCorpusCatalog(
        source_root=str(root),
        generated_at=datetime.now().isoformat(timespec="seconds"),
        document_count=len(entries),
        unique_document_count=len(first_by_hash),
        exact_duplicate_count=sum(1 for item in entries if item.exact_duplicate_of),
        atom_candidate_count=sum(1 for item in entries if item.atom_candidate),
        documents=entries,
        counts_by_project=_counts(item.project_name for item in entries),
        counts_by_project_type=_counts(item.project_type for item in entries),
        counts_by_document_kind=_counts(item.document_kind.value for item in entries),
        counts_by_knowledge_role=_counts(item.knowledge_role.value for item in entries),
        counts_by_quality_tier=_counts(item.quality_tier for item in entries),
    )


def write_reference_corpus_catalog(catalog: ReferenceCorpusCatalog, output_dir: Path) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "reference_corpus_catalog.json"
    csv_path = output_dir / "reference_corpus_catalog.csv"
    markdown_path = output_dir / "reference_corpus_catalog.md"

    payload = catalog.model_dump(mode="json") if hasattr(catalog, "model_dump") else catalog.dict()
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_csv(catalog, csv_path)
    markdown_path.write_text(render_reference_corpus_catalog(catalog), encoding="utf-8")
    return {"json": str(json_path), "csv": str(csv_path), "markdown": str(markdown_path)}


def render_reference_corpus_catalog(catalog: ReferenceCorpusCatalog) -> str:
    lines = [
        "# 安能 Markdown 参考语料分类目录",
        "",
        f"- 来源目录：`{catalog.source_root}`",
        f"- 生成时间：`{catalog.generated_at}`",
        f"- Markdown 文件：{catalog.document_count}",
        f"- 唯一内容：{catalog.unique_document_count}",
        f"- 完全重复副本：{catalog.exact_duplicate_count}",
        f"- 可进入原子候选池：{catalog.atom_candidate_count}",
        "",
        "## 知识用途",
        "",
        *_render_counts(catalog.counts_by_knowledge_role),
        "",
        "## 文档类型",
        "",
        *_render_counts(catalog.counts_by_document_kind),
        "",
        "## 项目类型",
        "",
        *_render_counts(catalog.counts_by_project_type),
        "",
        "## 质量分层",
        "",
        *_render_counts(catalog.counts_by_quality_tier),
        "",
        "## 原子候选文档",
        "",
        "| 项目 | 项目类型 | 文档类型 | 质量 | 文件 |",
        "| --- | --- | --- | --- | --- |",
    ]
    candidates = [item for item in catalog.documents if item.atom_candidate]
    for item in sorted(candidates, key=lambda value: (value.project_type, value.project_name, value.file_name))[:300]:
        lines.append(
            f"| {item.project_name} | {item.project_type} | {item.document_kind.value} | "
            f"{item.quality_tier} | `{item.relative_path}` |"
        )
    if len(candidates) > 300:
        lines.append(f"| - | - | - | - | 其余 {len(candidates) - 300} 份见 CSV/JSON |")
    lines.extend(
        [
            "",
            "## 使用边界",
            "",
            "- `project_evidence` 只在对应用户项目上传或明确补充时作为项目事实来源。",
            "- `reference_atom_source` 可以进入原子切分候选池，但其中项目参数不得直接迁移到其他项目。",
            "- `writing_guidance` 只提炼章节组织和检查闭环，不提供项目事实。",
            "- `quality_feedback` 用于评价方案常见缺陷和审批关注点，不直接生成正文。",
            "- `excluded` 和完全重复文档不进入原子切分与检索。",
        ]
    )
    return "\n".join(lines).strip() + "\n"


def _catalog_one(root: Path, path: Path) -> ReferenceDocumentEntry:
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    text = raw.decode("utf-8-sig", errors="replace")
    relative_path = path.relative_to(root).as_posix()
    project_name = _project_name(Path(relative_path), path.name)
    project_type = _project_type(project_name, relative_path, path.name)
    kind, role, reasons = _classify(relative_path, path.name, len(raw), text[:12000])
    metrics = _text_metrics(text)
    quality_tier, atom_candidate, exclusions = _quality(
        kind=kind,
        role=role,
        size_bytes=len(raw),
        metrics=metrics,
    )
    return ReferenceDocumentEntry(
        document_id=stable_id("refdoc", digest),
        content_hash=digest,
        absolute_path=str(path.resolve()),
        relative_path=relative_path,
        file_name=path.name,
        project_name=project_name,
        project_type=project_type,
        document_kind=kind,
        knowledge_role=role,
        classification_reasons=reasons,
        size_bytes=len(raw),
        quality_tier=quality_tier,
        atom_candidate=atom_candidate,
        exclusion_reasons=exclusions,
        **metrics,
    )


def _project_name(relative_path: Path, file_name: str) -> str:
    parts = list(relative_path.parts)
    if len(parts) >= 3 and parts[0] == "方案大模型资料" and parts[1] == "方案大模型资料":
        return parts[2]
    if parts and parts[0] == "施组及专项施工方案":
        for token, project in (
            ("安化", "安化"),
            ("靖宇", "靖宇"),
            ("昌邑", "昌邑"),
        ):
            if token in file_name:
                return project
        return "精选施组及专项方案"
    return "公共资料"


def _project_type(project_name: str, relative_path: str, file_name: str) -> str:
    if project_name in _PROJECT_TYPES:
        return _PROJECT_TYPES[project_name]
    text = f"{project_name} {relative_path} {file_name}"
    rules = (
        ("煤火", "煤火治理"),
        ("抽水蓄能", "抽水蓄能"),
        ("水电站", "水电"),
        ("导流洞", "水电/导流隧洞/边坡"),
        ("交通洞", "水电/地下洞室"),
        ("光伏", "光伏"),
        ("风电", "风电"),
        ("管网", "市政/管网"),
        ("水环境", "水环境/河道治理"),
    )
    return next((value for token, value in rules if token in text), "综合/待AI确认")


def _classify(relative_path: str, file_name: str, size_bytes: int, preview: str):
    identity = f"{relative_path}\n{file_name}"
    preview = preview[:4000]
    reasons: list[str] = []

    # File identity wins over words quoted in a TOC or body. Tender and contract
    # files routinely mention "施工组织设计" without being reusable plan sources.
    if relative_path.startswith("施组及专项施工方案/"):
        reasons.append("位于人工精选的施组及专项方案目录")
        kind = (
            ReferenceDocumentKind.construction_organization
            if re.search(r"施工组织设计|施组", file_name)
            else ReferenceDocumentKind.special_plan
        )
        return kind, KnowledgeRole.reference_atom_source, reasons
    if re.search(r"批复|审批|审查记录|专家论证|监理意见|咨询意见", file_name):
        reasons.append("文件名识别为审批、审查或专家意见")
        return ReferenceDocumentKind.approval_review, KnowledgeRole.quality_feedback, reasons
    if re.search(r"编写指南|编制指南|技术标准|规程规范|规范清单|管理办法", file_name):
        reasons.append("文件名识别为标准、指南或管理制度")
        return ReferenceDocumentKind.standard_guideline, KnowledgeRole.writing_guidance, reasons
    if re.search(r"合同|补充协议|分包协议", file_name):
        reasons.append("文件名识别为合同或协议")
        return ReferenceDocumentKind.contract, KnowledgeRole.project_evidence, reasons
    if re.search(r"投标文件|技术标书|投标技术|技术标", file_name):
        reasons.append("文件名识别为投标文件")
        return ReferenceDocumentKind.bid_document, KnowledgeRole.project_evidence, reasons
    if re.search(r"招标文件|招标技术|招标工程量|技术条款", file_name):
        reasons.append("文件名识别为招标文件")
        return ReferenceDocumentKind.tender_document, KnowledgeRole.project_evidence, reasons
    if re.search(r"报价|价格清单|工程量清单|电子清单", file_name):
        reasons.append("文件名识别为工程量或价格文件")
        return ReferenceDocumentKind.quantity_price, KnowledgeRole.project_evidence, reasons
    if re.search(r"图纸|施工图|布置图|结构图|设计说明|初步设计|初设报告|招标设计", file_name):
        reasons.append("文件名识别为设计或图纸转换文件")
        return ReferenceDocumentKind.design_drawing, KnowledgeRole.project_evidence, reasons

    if re.search(r"投标文件|招投标文件", relative_path):
        reasons.append("所在目录识别为投标文件")
        return ReferenceDocumentKind.bid_document, KnowledgeRole.project_evidence, reasons
    if re.search(r"招标文件", relative_path):
        reasons.append("所在目录识别为招标文件")
        return ReferenceDocumentKind.tender_document, KnowledgeRole.project_evidence, reasons
    if re.search(r"合同文件|主合同|对上合同|合同及补充协议", relative_path):
        reasons.append("所在目录识别为合同资料")
        return ReferenceDocumentKind.contract, KnowledgeRole.project_evidence, reasons
    if re.search(r"设计资料|图纸|图册|详细勘察", relative_path):
        reasons.append("所在目录识别为设计或图纸资料")
        return ReferenceDocumentKind.design_drawing, KnowledgeRole.project_evidence, reasons

    if re.search(r"施工组织设计|实施性施工组织设计|施工总组织", identity) and size_bytes >= 50_000:
        reasons.append("文件名或非证据目录路径识别为施工组织设计")
        return ReferenceDocumentKind.construction_organization, KnowledgeRole.reference_atom_source, reasons
    if re.search(r"专项施工方案|专项方案|施工方案", identity) and size_bytes >= 20_000:
        reasons.append("文件名或非证据目录路径识别为专项施工方案")
        return ReferenceDocumentKind.special_plan, KnowledgeRole.reference_atom_source, reasons
    if re.search(r"编写指南|编制指南|技术标准|规程规范|规范清单|管理办法", identity):
        reasons.append("路径识别为标准、指南或管理制度")
        return ReferenceDocumentKind.standard_guideline, KnowledgeRole.writing_guidance, reasons
    if re.search(r"批复|审批|审查记录|专家论证|监理意见|咨询意见", identity):
        reasons.append("路径识别为审批、审查或专家意见")
        return ReferenceDocumentKind.approval_review, KnowledgeRole.quality_feedback, reasons
    if re.search(r"澄清|补遗|地质|水文|气象|环保|水保|安全管理", identity):
        reasons.append("识别为项目补充资料")
        return ReferenceDocumentKind.project_support, KnowledgeRole.project_evidence, reasons
    if re.search(r"施工组织设计|实施性施工组织设计|施工总组织", preview) and size_bytes >= 100_000:
        reasons.append("仅正文出现施组特征，等待AI确认后方可进入候选池")
        return ReferenceDocumentKind.unknown, KnowledgeRole.unclassified, reasons
    reasons.append("规则无法确认文档用途，等待AI复核")
    return ReferenceDocumentKind.unknown, KnowledgeRole.unclassified, reasons


def _text_metrics(text: str) -> dict[str, int]:
    lines = text.splitlines()
    return {
        "char_count": len(text),
        "line_count": len(lines),
        "heading_count": sum(1 for line in lines if re.match(r"^#{1,6}\s+", line.strip())),
        "table_line_count": sum(1 for line in lines if line.lstrip().startswith("|")),
        "image_reference_count": len(re.findall(r"!\[[^\]]*]\([^)]+\)", text)),
        "replacement_char_count": text.count("\ufffd"),
    }


def _quality(*, kind, role, size_bytes: int, metrics: dict[str, int]):
    exclusions: list[str] = []
    if size_bytes < 512 or metrics["char_count"] < 200:
        exclusions.append("正文过短")
    if metrics["replacement_char_count"] > max(10, metrics["char_count"] // 100):
        exclusions.append("解码替换字符过多")
    if metrics["heading_count"] == 0 and metrics["char_count"] < 3000:
        exclusions.append("缺少标题结构且正文较短")
    if role in {KnowledgeRole.excluded, KnowledgeRole.unclassified}:
        exclusions.append("尚未确认知识用途")
    if kind in {ReferenceDocumentKind.design_drawing, ReferenceDocumentKind.quantity_price}:
        exclusions.append("图纸或清单不适合作为正文原子")

    atom_candidate = (
        role == KnowledgeRole.reference_atom_source
        and not exclusions
        and metrics["char_count"] >= 5000
        and metrics["heading_count"] >= 3
    )
    if atom_candidate and kind == ReferenceDocumentKind.construction_organization and metrics["char_count"] >= 100_000:
        tier = "A"
    elif atom_candidate and metrics["char_count"] >= 20_000:
        tier = "B"
    elif role in {KnowledgeRole.project_evidence, KnowledgeRole.writing_guidance, KnowledgeRole.quality_feedback} and not exclusions:
        tier = "C"
    else:
        tier = "D"
    return tier, atom_candidate, list(dict.fromkeys(exclusions))


def _counts(values) -> dict[str, int]:
    return dict(sorted(Counter(values).items(), key=lambda item: (-item[1], item[0])))


def _render_counts(counts: dict[str, int]) -> list[str]:
    return [f"- {key}: {value}" for key, value in counts.items()] or ["- 无"]


def _write_csv(catalog: ReferenceCorpusCatalog, path: Path) -> None:
    headers = [
        "标识",
        "项目",
        "项目类型",
        "文档类型",
        "知识用途",
        "质量等级",
        "原子候选",
        "相对路径",
        "文件名",
        "字节数",
        "字符数",
        "标题数",
        "内容哈希",
        "重复于",
        "分类依据",
        "排除原因",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        for item in catalog.documents:
            writer.writerow(
                [
                    item.document_id,
                    item.project_name,
                    item.project_type,
                    item.document_kind.value,
                    item.knowledge_role.value,
                    item.quality_tier,
                    "是" if item.atom_candidate else "否",
                    item.relative_path,
                    item.file_name,
                    item.size_bytes,
                    item.char_count,
                    item.heading_count,
                    item.content_hash,
                    item.exact_duplicate_of or "",
                    "；".join(item.classification_reasons),
                    "；".join(item.exclusion_reasons),
                ]
            )
