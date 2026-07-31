from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

from coalplan.application.reference_atom_retrieval import (
    audit_reference_atom_leakage,
    build_reference_leakage_repair_prompt,
    render_reference_atoms_for_prompt,
    retrieve_reference_atoms,
)
from coalplan.application.reference_atomization import atomize_reference_markdown
from coalplan.application.serialization import dump_model, to_json_text
from coalplan.domain.documents import stable_id
from coalplan.domain.reference_library import (
    AtomRetrievalQuery,
    ReferenceDocument,
    ReferenceDocumentKind,
    ReferenceReviewStatus,
)
from coalplan.infrastructure.database.reference_repository import ReferenceLibraryRepository
from coalplan.infrastructure.database.session import create_session_factory, init_database, sqlite_url_for_storage
from coalplan.infrastructure.llm.openai_compatible import OpenAICompatibleLLMClient
from coalplan.infrastructure.markdown.parser import MarkdownDocumentParser
from coalplan.settings import get_settings


CORPUS_ROOT = Path(r"D:\Task_md\安能-数据-markdown")
SAMPLE_ROOT = Path(r"C:\Users\Lenovo\Desktop\示例输入输出\project_4")
OUTPUT_ROOT = Path(".coalplan-data/reference-library/validation/lawa_cross_project")
PROCESS_TERMS = [
    "测量放样",
    "钻孔",
    "装药",
    "爆破",
    "通风",
    "排烟",
    "安全检查",
    "出渣",
    "初期支护",
    "超欠挖",
    "监测",
    "验收",
    "记录",
]
CONTROL_TERMS = ["工序", "检查", "复核", "质量", "安全", "围岩", "地质", "支护", "反馈", "闭环"]


def main() -> int:
    settings = get_settings()
    if not settings.deepseek_api_key:
        raise RuntimeError("COALPLAN_DEEPSEEK_API_KEY is required for the real validation run.")
    output_dir = OUTPUT_ROOT.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    llm = OpenAICompatibleLLMClient(
        base_url=settings.deepseek_base_url,
        api_key=settings.deepseek_api_key,
        model=settings.deepseek_model,
        disable_thinking=True,
        trace_dir=output_dir / "traces",
    )
    session_factory = create_session_factory(sqlite_url_for_storage(output_dir))
    init_database(session_factory)
    repository = ReferenceLibraryRepository(session_factory)

    source_specs = [
        (
            _find_one(CORPUS_ROOT, "导流洞洞挖专项施工方案.md"),
            "扎拉",
            "水电/导流隧洞/边坡",
            817,
            1055,
        ),
        (
            _find_one(CORPUS_ROOT / "施组及专项施工方案", "靖宇项目《进厂交通洞洞身段开挖支护专项施工方案》.md"),
            "靖宇",
            "抽水蓄能/交通洞",
            700,
            1050,
        ),
    ]
    atomization_summary: list[dict] = []
    for path, project_name, project_type, start_line, end_line in source_specs:
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        document = ReferenceDocument(
            id=stable_id("refdoc", digest),
            content_hash=digest,
            source_path=str(path),
            file_name=path.name,
            project_name=project_name,
            project_type=project_type,
            document_kind=ReferenceDocumentKind.special_plan,
        )
        repository.save_document(document)
        full_text = raw.decode("utf-8-sig", errors="replace")
        excerpt = "\n".join(full_text.splitlines()[start_line - 1 : end_line])
        result = atomize_reference_markdown(
            document=document,
            markdown=excerpt,
            llm=llm,
            max_batches=1,
            publish_for_validation=True,
        )
        repository.replace_document_content(document.id, chapters=[], atoms=result.atoms)
        atomization_summary.append(
            {
                "document": dump_model(document),
                "source_line_window": [start_line, end_line],
                "block_count": len(result.blocks),
                "atom_count": len(result.atoms),
                "published_count": sum(atom.status == ReferenceReviewStatus.published for atom in result.atoms),
                "llm_call_count": result.llm_call_count,
            }
        )

    bid_path = _find_one(SAMPLE_ROOT, "投标文档（md版本）.md")
    bid_markdown = bid_path.read_text(encoding="utf-8-sig", errors="replace")
    evidence = _lawa_evidence(bid_markdown, bid_path.name)
    query = AtomRetrievalQuery(
        project_name="金沙江上游拉哇水电站泄洪系统工程",
        project_type="水电/泄洪洞",
        chapter_title="泄洪洞洞身开挖与支护",
        parent_titles=["主要施工方法", "地下洞室工程"],
        evidence_summary=evidence[:6000],
        writing_topics=["钻爆开挖", "通风排烟", "出渣", "初期支护", "质量检查", "安全控制", "记录闭环"],
        top_k=5,
        excluded_project_names=["拉哇", "10.拉哇项目部"],
    )
    atoms = repository.list_atoms(status=ReferenceReviewStatus.published)
    if not atoms:
        raise RuntimeError("AI atomization produced no high-confidence published atoms; inspect trace output.")
    results = retrieve_reference_atoms(atoms=atoms, query=query, llm=llm)
    if not results:
        raise RuntimeError("AI rerank selected no cross-project reference atoms; inspect trace output.")

    baseline_prompt = _generation_prompt(evidence=evidence, reference_atoms="")
    enhanced_prompt = _generation_prompt(
        evidence=evidence,
        reference_atoms=render_reference_atoms_for_prompt(results),
    )
    baseline = llm.complete(baseline_prompt)
    enhanced = llm.complete(enhanced_prompt)
    initial_leakage = audit_reference_atom_leakage(
        generated_markdown=enhanced,
        results=results,
        trusted_project_text=evidence,
    )
    safe_enhanced = enhanced
    if initial_leakage:
        safe_enhanced = llm.complete(
            build_reference_leakage_repair_prompt(
                generated_markdown=enhanced,
                issues=initial_leakage,
                trusted_project_text=evidence,
            )
        )
    leakage = audit_reference_atom_leakage(
        generated_markdown=safe_enhanced,
        results=results,
        trusted_project_text=evidence,
    )
    metrics = {
        "baseline": _metrics(baseline),
        "enhanced_raw": _metrics(enhanced),
        "enhanced": _metrics(safe_enhanced),
        "delta": {
            "process_coverage": _metrics(safe_enhanced)["process_coverage"] - _metrics(baseline)["process_coverage"],
            "control_coverage": _metrics(safe_enhanced)["control_coverage"] - _metrics(baseline)["control_coverage"],
            "char_count": len(safe_enhanced) - len(baseline),
        },
        "initial_reference_atom_leakage_issue_count": len(initial_leakage),
        "reference_atom_leakage_issue_count": len(leakage),
    }
    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "target_project": query.project_name,
        "target_bid_path": str(bid_path),
        "reference_project_exclusion": ["拉哇", "10.拉哇项目部"],
        "atomization": atomization_summary,
        "retrieval_query": dump_model(query),
        "retrieval_results": [dump_model(item) for item in results],
        "metrics": metrics,
        "initial_leakage_issues": [dump_model(item) for item in initial_leakage],
        "leakage_issues": [dump_model(item) for item in leakage],
        "llm_model": settings.deepseek_model,
        "expected_llm_calls": 5 + (1 if initial_leakage else 0),
    }
    (output_dir / "baseline.md").write_text(baseline, encoding="utf-8")
    (output_dir / "enhanced_raw.md").write_text(enhanced, encoding="utf-8")
    (output_dir / "enhanced.md").write_text(safe_enhanced, encoding="utf-8")
    (output_dir / "retrieved_atoms.md").write_text(render_reference_atoms_for_prompt(results), encoding="utf-8")
    (output_dir / "validation.json").write_text(to_json_text(payload), encoding="utf-8")
    (output_dir / "validation_report.md").write_text(_report(payload), encoding="utf-8")
    print(json.dumps({"output_dir": str(output_dir), **metrics}, ensure_ascii=False, indent=2))
    return 0


def _lawa_evidence(markdown: str, file_name: str) -> str:
    sections = MarkdownDocumentParser().split_sections(markdown, source_file=file_name)
    selected = [
        section
        for section in sections
        if any(token in section.path_text for token in ("3.4.4 溢洪洞洞挖施工", "3.4.5 泄洪洞洞挖施工"))
        and section.content.strip()
    ]
    selected.sort(key=lambda item: item.start_line or 0)
    blocks: list[str] = []
    total = 0
    for section in selected:
        block = (
            f"[section_id={section.id}; title_path={section.path_text}; "
            f"lines={section.start_line}-{section.end_line}]\n{section.content}"
        )
        if total + len(block) > 24000:
            remaining = 24000 - total
            if remaining > 1000:
                blocks.append(block[:remaining])
            break
        blocks.append(block)
        total += len(block)
    if not blocks:
        raise RuntimeError("Could not locate Lawa 3.4.4/3.4.5 evidence sections.")
    return "\n\n".join(blocks)


def _generation_prompt(*, evidence: str, reference_atoms: str) -> str:
    atom_block = reference_atoms or "本轮为基线，不提供优秀施组参考原子。"
    return f"""你是施工组织设计正文生成助手。请为“金沙江上游拉哇水电站泄洪系统工程”编写：
# 泄洪洞洞身开挖与支护

## 当前项目投标证据（唯一项目事实来源）
{evidence}

## 优秀施组参考原子（异项目、非事实来源）
{atom_block}

硬性约束：
1. 当前项目的断面、工程量、围岩、设备数量、参数、地名、日期和规范编号只能来自当前项目投标证据。
2. 参考原子只可用于补足工艺步骤、控制维度、检查验收闭环和专业表达，不得整段照搬。
3. 参考原子与当前项目证据冲突时以当前项目证据为准；证据缺失则写【需人工补充：具体内容】。
4. 正文应按实际工序展开，覆盖测量放样、钻孔、装药联网、爆破、通风排烟、安全检查、出渣、初期支护中有证据或可作通用逻辑的环节，并说明质量、安全、监测、验收和记录闭环。
5. 不得声称已经完成检查、验收、审批或监测；只能写施工阶段应执行的措施。

只输出 Markdown，包含：
# 泄洪洞洞身开挖与支护
## 主要来源摘要
## 生成正文
## 人工补充需补充
目标 1800~2400 个汉字。"""


def _metrics(markdown: str) -> dict:
    process_hits = [term for term in PROCESS_TERMS if term in markdown]
    control_hits = [term for term in CONTROL_TERMS if term in markdown]
    return {
        "char_count": len(markdown),
        "process_hits": process_hits,
        "process_coverage": round(len(process_hits) / len(PROCESS_TERMS), 3),
        "control_hits": control_hits,
        "control_coverage": round(len(control_hits) / len(CONTROL_TERMS), 3),
        "manual_placeholder_count": markdown.count("【需人工补充："),
    }


def _report(payload: dict) -> str:
    baseline = payload["metrics"]["baseline"]
    enhanced = payload["metrics"]["enhanced"]
    lines = [
        "# 拉哇跨项目原子增强验证报告",
        "",
        f"- 目标项目：{payload['target_project']}",
        f"- 模型：{payload['llm_model']}",
        f"- 原子来源项目：{', '.join(item['document']['project_name'] for item in payload['atomization'])}",
        "- 强制排除：拉哇项目自身参考施组",
        f"- 召回原子：{len(payload['retrieval_results'])}",
        f"- 参考事实泄漏问题：{payload['metrics']['reference_atom_leakage_issue_count']}",
        f"- 自动修复前泄漏问题：{payload['metrics']['initial_reference_atom_leakage_issue_count']}",
        "",
        "## 对比指标",
        "",
        "| 指标 | 基线 | 原子增强 | 差值 |",
        "| --- | ---: | ---: | ---: |",
        f"| 工序词覆盖率 | {baseline['process_coverage']:.3f} | {enhanced['process_coverage']:.3f} | {payload['metrics']['delta']['process_coverage']:+.3f} |",
        f"| 控制闭环词覆盖率 | {baseline['control_coverage']:.3f} | {enhanced['control_coverage']:.3f} | {payload['metrics']['delta']['control_coverage']:+.3f} |",
        f"| 字符数 | {baseline['char_count']} | {enhanced['char_count']} | {payload['metrics']['delta']['char_count']:+d} |",
        f"| 人工补充占位 | {baseline['manual_placeholder_count']} | {enhanced['manual_placeholder_count']} | - |",
        "",
        "## 召回记录",
        "",
    ]
    for item in payload["retrieval_results"]:
        lines.append(
            f"- `{item['atom_id']}`：{item['atom']['project_name']} / "
            f"{' > '.join(item['atom']['title_path'])}；score={item['score']:.3f}；{item['match_reason']}"
        )
    lines.extend(
        [
            "",
            "## 验证边界",
            "",
            "- 本次只验证一个真实章节、两个异项目来源和六次以内真实模型调用，不代表全库批量质量。",
            "- 指标用于比较同一证据条件下工序及控制要点覆盖变化，最终技术正确性仍需专业人员审核。",
            "- 详细提示词与模型返回见 `traces/`，生成正文见 `baseline.md` 和 `enhanced.md`。",
        ]
    )
    return "\n".join(lines) + "\n"


def _find_one(root: Path, file_name: str) -> Path:
    matches = list(root.rglob(file_name))
    if len(matches) != 1:
        raise RuntimeError(f"Expected one match for {file_name}, got {len(matches)}.")
    return matches[0]


if __name__ == "__main__":
    raise SystemExit(main())
