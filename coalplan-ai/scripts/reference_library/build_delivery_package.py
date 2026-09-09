from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import tempfile
import zipfile
from collections import Counter
from datetime import datetime
from pathlib import Path


CATEGORIES = ("施组文档", "投标文档", "专项计划")
CORPUS_DIRECTORIES = ("documents", "routes", "validation")
CORPUS_FILES = (
    "atom_catalog.v2.json",
    "atom_catalog.v2.md",
    "corpus_manifest.v2.json",
    "curation_report.v2.json",
    "database_sync_summary.v2.json",
    "routing_summary.v2.json",
    "run_summary.v2.json",
    "starter_publish_selection.v2.json",
    "retrieval_validation_publish_selection.v2.json",
    "retrieval_validation_regression.v2.json",
)
CLEANING_REPORTS = (
    "保留文档.csv",
    "排除文档.csv",
    "清洗报告.md",
    "清洗汇总.json",
    "全部文件判定.csv",
    "clean_corpus.py",
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a data-only reference-library delivery package.")
    parser.add_argument("--cleaned-root", type=Path, required=True)
    parser.add_argument("--corpus-root", type=Path, required=True)
    parser.add_argument("--vector-root", type=Path, required=True)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--taxonomy", type=Path, required=True)
    parser.add_argument("--schemas", type=Path, required=True)
    parser.add_argument("--architecture-doc", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    inputs = {
        "cleaned_root": args.cleaned_root.resolve(),
        "corpus_root": args.corpus_root.resolve(),
        "vector_root": args.vector_root.resolve(),
        "database": args.database.resolve(),
        "taxonomy": args.taxonomy.resolve(),
        "schemas": args.schemas.resolve(),
        "architecture_doc": args.architecture_doc.resolve(),
    }
    _validate_inputs(inputs)
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="coalplan-reference-delivery-", dir=output.parent) as temporary:
        root = Path(temporary) / output.stem
        cleaning_summary = _copy_cleaned_documents(
            inputs["cleaned_root"], inputs["corpus_root"], root / "01_清洗文档"
        )
        export_summary = _export_library(inputs["database"], root / "02_原子库" / "library_export")
        export_summary.update(cleaning_summary)
        _copy_corpus_assets(inputs["corpus_root"], root / "02_原子库" / "processing_assets")
        shutil.copytree(inputs["vector_root"], root / "03_向量索引" / "reference-vectors")
        _write_documentation(root, inputs, export_summary)
        _write_manifest(root)
        _zip_tree(root, output)

    print(json.dumps({
        "output": str(output),
        "size_bytes": output.stat().st_size,
        **export_summary,
    }, ensure_ascii=False, indent=2))
    return 0


def _validate_inputs(inputs: dict[str, Path]) -> None:
    for name, path in inputs.items():
        if not path.exists():
            raise FileNotFoundError(f"Missing {name}: {path}")
    for category in CATEGORIES:
        if not (inputs["cleaned_root"] / category).is_dir():
            raise FileNotFoundError(f"Missing cleaned category: {category}")


def _copy_cleaned_documents(source: Path, corpus_root: Path, target: Path) -> dict:
    target.mkdir(parents=True, exist_ok=True)
    excluded = _atomization_exclusions(corpus_root)
    category_counts: dict[str, int] = {}
    for category in CATEGORIES:
        category_target = target / category
        count = 0
        for path in sorted(item for item in (source / category).rglob("*") if item.is_file()):
            if path.resolve() in excluded:
                continue
            destination = category_target / path.relative_to(source / category)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, destination)
            count += 1
        category_counts[category] = count
    report_dir = target / "清洗过程与清单"
    report_dir.mkdir(parents=True, exist_ok=True)
    for name in CLEANING_REPORTS:
        path = source / name
        if path.exists():
            shutil.copy2(path, report_dir / name)
    if excluded:
        lines = ["# 原子化复核追加排除", ""]
        lines.extend(f"- `{path}`：全文为报审、通知、会议议程或签批记录，无可用技术原子。" for path in sorted(excluded))
        (report_dir / "原子化复核追加排除.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {
        "cleaned_category_counts": category_counts,
        "atomization_excluded_document_count": len(excluded),
    }


def _atomization_exclusions(corpus_root: Path) -> set[Path]:
    excluded: set[Path] = set()
    for path in (corpus_root / "documents").glob("*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            continue
        if payload.get("status") != "excluded_no_technical_content":
            continue
        source_path = ((payload.get("document") or {}).get("source_path") or "").strip()
        if source_path:
            excluded.add(Path(source_path).resolve())
    return excluded


def _copy_corpus_assets(source: Path, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    for name in CORPUS_DIRECTORIES:
        path = source / name
        if path.exists():
            shutil.copytree(path, target / name)
    for name in CORPUS_FILES:
        path = source / name
        if path.exists():
            shutil.copy2(path, target / name)


def _export_library(database: Path, target: Path) -> dict[str, int | dict[str, int]]:
    target.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        atom_rows = connection.execute(
            "SELECT * FROM reference_atoms "
            "WHERE json_extract(tags_json, '$.schema_version') = 'v2' ORDER BY id"
        ).fetchall()
        document_ids = sorted({str(row["document_id"]) for row in atom_rows})
        placeholders = ",".join("?" for _ in document_ids)
        document_rows = connection.execute(
            f"SELECT * FROM reference_documents WHERE id IN ({placeholders}) ORDER BY file_name, id",
            document_ids,
        ).fetchall()
        chapter_rows = connection.execute(
            f"SELECT * FROM reference_chapters WHERE document_id IN ({placeholders}) "
            "ORDER BY document_id, sort_order, id",
            document_ids,
        ).fetchall()
    finally:
        connection.close()

    chapter_payloads = [_chapter_payload(row) for row in chapter_rows]
    if not chapter_payloads:
        chapter_payloads = _derive_chapter_payloads(atom_rows)

    _write_jsonl(target / "reference_documents.jsonl", (_document_payload(row) for row in document_rows))
    _write_jsonl(target / "reference_chapters.jsonl", chapter_payloads)
    _write_jsonl(target / "reference_atoms_v2.jsonl", (_atom_payload(row) for row in atom_rows))
    status_counts = Counter(str(row["status"]) for row in atom_rows)
    summary = {
        "document_count": len(document_rows),
        "chapter_count": len(chapter_payloads),
        "chapter_index_source": "database" if chapter_rows else "derived_from_reference_atoms_v2",
        "atom_count": len(atom_rows),
        "status_counts": dict(sorted(status_counts.items())),
    }
    (target / "export_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return summary


def _document_payload(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "content_hash": row["content_hash"],
        "source_path": row["source_path"],
        "file_name": row["file_name"],
        "project_name": row["project_name"],
        "project_type": row["project_type"],
        "document_kind": row["document_kind"],
        "status": row["status"],
        "version": row["version"],
    }


def _chapter_payload(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "document_id": row["document_id"],
        "title_path": _json_value(row["title_path_json"], []),
        "start_line": row["start_line"],
        "end_line": row["end_line"],
        "sort_order": row["sort_order"],
        "derived_from": "reference_chapters",
    }


def _derive_chapter_payloads(atom_rows: list[sqlite3.Row]) -> list[dict]:
    grouped: dict[tuple[str, tuple[str, ...]], dict] = {}
    for row in atom_rows:
        title_path = tuple(str(item) for item in _json_value(row["title_path_json"], []) if str(item).strip())
        key = (str(row["document_id"]), title_path)
        start_line = int(row["start_line"] or 0)
        end_line = int(row["end_line"] or start_line)
        current = grouped.get(key)
        if current is None:
            grouped[key] = {
                "document_id": key[0],
                "title_path": list(title_path),
                "start_line": start_line,
                "end_line": end_line,
            }
            continue
        positive_starts = [value for value in (current["start_line"], start_line) if value > 0]
        current["start_line"] = min(positive_starts) if positive_starts else 0
        current["end_line"] = max(current["end_line"], end_line)

    ordered = sorted(
        grouped.values(),
        key=lambda item: (item["document_id"], item["start_line"], item["title_path"]),
    )
    per_document_order: Counter[str] = Counter()
    payloads: list[dict] = []
    for item in ordered:
        document_id = item["document_id"]
        per_document_order[document_id] += 1
        identity = json.dumps(
            [document_id, item["title_path"], item["start_line"], item["end_line"]],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        payloads.append({
            "id": f"refchapteridx_{hashlib.sha256(identity.encode('utf-8')).hexdigest()[:12]}",
            **item,
            "sort_order": per_document_order[document_id],
            "derived_from": "reference_atoms_v2",
        })
    return payloads


def _atom_payload(row: sqlite3.Row) -> dict:
    tags = _json_value(row["tags_json"], {})
    return {
        "id": row["id"],
        "document_id": row["document_id"],
        "project_name": row["project_name"],
        "project_type": row["project_type"],
        "title_path": _json_value(row["title_path_json"], []),
        "content": row["content"],
        "source_block_ids": _json_value(row["source_block_ids_json"], []),
        "start_line": row["start_line"],
        "end_line": row["end_line"],
        **tags,
        "applicability": _json_value(row["applicability_json"], []),
        "prohibited_scenarios": _json_value(row["prohibited_scenarios_json"], []),
        "fact_variables": _json_value(row["fact_variables_json"], []),
        "quality_score": row["quality_score"],
        "confidence": row["confidence"],
        "status": row["status"],
        "version": row["version"],
    }


def _json_value(value: str, default):
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


def _write_jsonl(path: Path, items) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for item in items:
            stream.write(json.dumps(item, ensure_ascii=False, separators=(",", ":")) + "\n")


def _write_documentation(root: Path, inputs: dict[str, Path], summary: dict) -> None:
    docs = root / "04_配置与说明"
    docs.mkdir(parents=True, exist_ok=True)
    shutil.copytree(inputs["schemas"], docs / "config" / "reference_library")
    shutil.copy2(inputs["architecture_doc"], docs / "原子库V2架构与运行说明.md")
    taxonomy = json.loads(inputs["taxonomy"].read_text(encoding="utf-8-sig"))
    (docs / "全部标签与别名.md").write_text(_taxonomy_markdown(taxonomy), encoding="utf-8")
    (docs / "数据字典.md").write_text(_data_dictionary(), encoding="utf-8")
    (docs / "向量索引使用说明.md").write_text(_vector_guide(), encoding="utf-8")
    (root / "README.md").write_text(_package_readme(summary), encoding="utf-8")


def _taxonomy_markdown(taxonomy: dict) -> str:
    labels = taxonomy.get("display_labels", {})
    sections = ["# 原子库 V2 全部受控标签", ""]
    for key, title in (
        ("chapter_modules", "章节模块 chapter_modules"),
        ("atom_types", "原子类型 atom_types"),
        ("process_stages", "工序阶段 process_stages"),
        ("content_functions", "内容功能 content_functions"),
        ("engineering_systems", "工程系统 engineering_systems"),
        ("process_families", "工艺族 process_families"),
        ("parameter_roles", "参数角色 parameter_roles"),
        ("reuse_policies", "复用策略 reuse_policies"),
    ):
        sections.extend([f"## {title}", ""])
        for value in taxonomy.get(key, []):
            display = labels.get(value)
            sections.append(f"- `{value}`" + (f"：{display}" if display else ""))
        sections.append("")
    sections.extend(["## 别名归一", ""])
    for group, aliases in taxonomy.get("aliases", {}).items():
        sections.append(f"### {group}")
        sections.extend(f"- `{alias}` → `{canonical}`" for alias, canonical in aliases.items())
        sections.append("")
    return "\n".join(sections).rstrip() + "\n"


def _data_dictionary() -> str:
    return """# 原子库数据字典

## library_export

- `reference_documents.jsonl`：参考施组来源文档，一行一份文档。
- `reference_chapters.jsonl`：标题路径和原文行号，用于溯源。若 V2 文档未写入旧版章节表，本文件由原子的标题路径与行号聚合生成，并以 `derived_from` 明确标识来源。
- `reference_atoms_v2.jsonl`：V2原子快照，一行一条原子。

## 原子核心字段

- `raw_excerpt`：可回查的原文引文。
- `normalized_text`：清理重复行和页码后的文本。
- `parameterized_template`：将历史项目参数替换为槽位后的生成参考文本。
- `chapter_module`、`engineering_system`、`engineering_object`、`process_family`、`process_stage`：检索主标签。
- `content_functions`：流程、方法、参数、质量、安全、验收、记录等功能。
- `action_sequence`、`control_points`、`acceptance_checks`、`exceptions`、`risks`：结构化技术内容。
- `parameter_slots`：参数原值、单位、角色、复用策略和原文位置。
- `publication_blockers`：发布前必须解决的阻断问题。
- `status`：只有 `published` 原子可进入章节生成。

## 事实边界

原子库提供工艺展开方式、控制逻辑和专业表达，不提供新项目事实。数值、地名、工程量、设备型号和规范版本须由当前投标证据、用户确认或试验设计提供。
"""


def _vector_guide() -> str:
    return """# 向量索引使用说明

## 内容

`03_向量索引/reference-vectors/` 是 Qdrant 本地持久化目录，集合名为 `reference_atoms_v2`。向量模型为 `BAAI/bge-small-zh-v1.5`，相似度使用 Cosine。

Qdrant 只保存数值向量和用于过滤的标签 payload，完整原子正文以 `02_原子库/library_export/reference_atoms_v2.jsonl` 为准。

## 项目配置

```powershell
pip install -e ".[reference-vector]"
$env:COALPLAN_REFERENCE_VECTOR_ENABLED="true"
$env:COALPLAN_REFERENCE_VECTOR_MODEL="BAAI/bge-small-zh-v1.5"
$env:COALPLAN_REFERENCE_VECTOR_PATH="reference-vectors"
```

将 `reference-vectors` 复制到项目的 `COALPLAN_STORAGE_DIR` 下即可使用本地索引。如果改用独立 Qdrant 服务，设置 `COALPLAN_REFERENCE_VECTOR_URL`并从已发布原子重建索引。

## 检索链路

```text
项目全局信息 + 父级目录 + 当前章节 + 投标证据摘要 + 写作任务
  -> AI受控标签分类
  -> 章节模块/工程系统/工艺族过滤
  -> 词法召回 + BGE向量召回
  -> RRF融合 + 工程对象/工序阶段/内容功能/质量分重排
```

只有 `schema_version=v2`、`status=published` 且无 `publication_blockers` 的原子可写入索引。原子被退回、排除或删除时，应同步从 Qdrant 删除。
"""


def _package_readme(summary: dict) -> str:
    statuses = "、".join(f"{key}={value}" for key, value in summary["status_counts"].items())
    categories = summary.get("cleaned_category_counts") or {}
    return f"""# 施工组织设计语料与原子库交付包

生成时间：{datetime.now().isoformat(timespec='seconds')}

## 目录

- `01_清洗文档/`：已分为施组文档、投标文档、专项计划，同时保留清洗报告和取舍清单。
- `02_原子库/library_export/`：从项目 SQLite 导出的独立 V2 数据快照。
- `02_原子库/processing_assets/`：路由、原子物化、去重冲突和真实检索验证产物。
- `03_向量索引/`：Qdrant/BGE 本地向量索引。
- `04_配置与说明/`：全部标签、AI输出Schema、数据字典、架构和使用说明。
- `05_清单校验/manifest.json`：所有打包文件的大小和 SHA-256。

## 数据概况

- 有效参考文档：{summary['document_count']} 份。
- 可溯源章节节点：{summary['chapter_count']} 个。
- V2 原子：{summary['atom_count']} 条。
- 当前状态：{statuses}。

## 清洗分类

- 施组文档：{categories.get('施组文档', 0)} 份，用于抽取工艺、控制、检查和组织逻辑原子。
- 投标文档：{categories.get('投标文档', 0)} 份，作为后续项目事实证据样本，不与优秀施组原子混库。
- 专项计划：{categories.get('专项计划', 0)} 份，作为专项施工范围的参考语料，需根据文档性质决定是否进入原子化。

签名页、封面、空白附件、重复件和缺少实质技术内容的文档已按清洗清单排除。具体去留原因查看 `01_清洗文档/清洗过程与清单/`。

## 使用边界

原子中的历史项目数值、规范版本、设备型号和管理主体不得直接迁移至新项目。当前项目事实只能来自投标证据、用户确认或当前项目试验设计。

本包不包含 `.env`、API Key、用户项目数据库、章节使用记录、模型原始调用轨迹和可续跑检查点。
"""


def _write_manifest(root: Path) -> None:
    target = root / "05_清单校验"
    target.mkdir(parents=True, exist_ok=True)
    files = []
    for path in sorted(item for item in root.rglob("*") if item.is_file() and target not in item.parents):
        files.append({
            "path": path.relative_to(root).as_posix(),
            "size_bytes": path.stat().st_size,
            "sha256": _sha256(path),
        })
    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "file_count": len(files),
        "total_bytes": sum(item["size_bytes"] for item in files),
        "files": files,
    }
    (target / "manifest.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _zip_tree(root: Path, output: Path) -> None:
    temporary = output.with_suffix(output.suffix + ".tmp")
    if temporary.exists():
        temporary.unlink()
    with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(item for item in root.rglob("*") if item.is_file()):
            archive.write(path, (Path(root.name) / path.relative_to(root)).as_posix())
    temporary.replace(output)


if __name__ == "__main__":
    raise SystemExit(main())
