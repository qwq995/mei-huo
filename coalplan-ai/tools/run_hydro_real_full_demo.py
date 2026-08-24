"""Run one isolated, real-model hydro generation and compliance review demo."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from coalplan.application.compliance_review import run_compliance_review
from coalplan.application.serialization import to_json_text
from coalplan.infrastructure.database.standard_repository import StandardConstraintRepository
from coalplan.main import build_pipeline
from coalplan.settings import Settings

from run_deepseek_full_generation import (
    PROJECT_CONFIGS,
    _run_one,
    _trace_usage_summary,
)
from seed_hydro_demo_library import seed


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Run one real full hydro generation with atom and standards tracing.")
    parser.add_argument("--input-root", type=Path, default=Path.home() / "Desktop" / "示例输入输出")
    parser.add_argument("--output-root", type=Path, default=None)
    args = parser.parse_args()

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    output_root = (args.output_root or Path.cwd() / f".coalplan-hydro-real-full-{timestamp}").resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    storage_dir = output_root / "storage"
    traces_dir = output_root / "traces"

    manifest = seed(storage_dir)
    settings = Settings(
        storage_dir=storage_dir,
        llm_provider="deepseek",
        structured_llm_provider="deepseek",
        llm_trace_dir=traces_dir,
        deepseek_api_key=os.getenv("COALPLAN_DEEPSEEK_API_KEY", ""),
        deepseek_base_url=os.getenv("COALPLAN_DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        deepseek_model=os.getenv("COALPLAN_DEEPSEEK_MODEL", "deepseek-v4-pro"),
    )
    if not settings.deepseek_api_key:
        raise RuntimeError("COALPLAN_DEEPSEEK_API_KEY is required.")

    print(f"[1/4] 已创建隔离库：{storage_dir}", flush=True)
    print(f"      参考原子={manifest['reference_atom_count']}，规范条例={manifest['constraint_atom_count']}", flush=True)
    pipeline = build_pipeline(settings)
    trace_start = _trace_usage_summary(traces_dir)

    started = time.perf_counter()
    print("[2/4] 开始真实全量生成：拉哇水电投标样例 + hydro_diversion_slope 模板", flush=True)
    generated = _run_one(
        pipeline,
        input_root=args.input_root,
        output_root=output_root,
        quality_dir=output_root / "quality_audit",
        demo={"key": "project_4", **PROJECT_CONFIGS["project_4"]},
        max_retries=1,
        chapter_limit=None,
        chapter_title_contains=[],
    )
    generation_seconds = round(time.perf_counter() - started, 3)
    project_id = generated["project_id"]
    print(f"[3/4] 全量生成完成：{generated['task_count']} 个章节任务，耗时 {generation_seconds}s", flush=True)

    print("[4/4] 开始对合并成稿执行真实规范符合性审查", flush=True)
    standard_repository = StandardConstraintRepository(pipeline.workspace_store.session_factory)

    def progress(stage: str, current: int, total: int, message: str) -> None:
        print(f"      [{stage}] {current}/{total} {message}", flush=True)

    review_started = time.perf_counter()
    review = run_compliance_review(
        project_id=project_id,
        pipeline=pipeline,
        repository=standard_repository,
        progress=progress,
    )
    review_seconds = round(time.perf_counter() - review_started, 3)
    trace_end = _trace_usage_summary(traces_dir)

    usage_records = pipeline.reference_library.list_usage(project_id)
    atom_details = _atom_usage_details(pipeline, usage_records)
    review_run = review.get("run") or {}
    run_id = review_run.get("id")
    constraint_matches = []
    if run_id:
        constraint_matches = [
            item.model_dump(mode="json")
            for item in standard_repository.list_constraint_matches(project_id, run_id)
        ]
    documents = {item.id: item for item in standard_repository.list_documents()}
    constraint_atoms = {item.id: item for item in standard_repository.list_atoms()}
    findings = review.get("findings") or []

    report = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "model": settings.deepseek_model,
        "provider": "deepseek",
        "input_root": str(args.input_root.resolve()),
        "output_root": str(output_root),
        "project_id": project_id,
        "generation": generated,
        "timing": {"generation_seconds": generation_seconds, "review_seconds": review_seconds},
        "reference_atom_usage": {
            "record_count": len(usage_records),
            "distinct_atom_count": len({item.get("atom_id") for item in usage_records}),
            "by_atom": atom_details,
            "records": usage_records,
        },
        "compliance_review": {
            "run": review_run,
            "standard_matches": review.get("standard_matches") or [],
            "constraint_match_count": len(constraint_matches),
            "constraint_matches": [
                {
                    **item,
                    "standard_name": documents.get(item["document_id"]).name if documents.get(item["document_id"]) else "",
                    "clause_no": constraint_atoms.get(item["atom_id"]).clause_no if constraint_atoms.get(item["atom_id"]) else "",
                    "normalized_requirement": constraint_atoms.get(item["atom_id"]).normalized_requirement if constraint_atoms.get(item["atom_id"]) else "",
                }
                for item in constraint_matches
            ],
            "findings": findings,
            "finding_count": len(findings),
            "open_count": review.get("open_count", 0),
            "warnings": review.get("warnings") or [],
        },
        "llm_usage": {
            "before": trace_start,
            "after": trace_end,
            "call_count": trace_end["call_count"] - trace_start["call_count"],
            "prompt_tokens": trace_end["prompt_tokens"] - trace_start["prompt_tokens"],
            "completion_tokens": trace_end["completion_tokens"] - trace_start["completion_tokens"],
            "total_tokens": trace_end["total_tokens"] - trace_start["total_tokens"],
            "estimated_total_tokens": trace_end["estimated_total_tokens"] - trace_start["estimated_total_tokens"],
            "prompt_char_total": trace_end["prompt_char_total"] - trace_start["prompt_char_total"],
            "response_char_total": trace_end["response_char_total"] - trace_start["response_char_total"],
            "elapsed_seconds_total": round(trace_end["elapsed_seconds_total"] - trace_start["elapsed_seconds_total"], 3),
            "error_count": trace_end["error_count"] - trace_start["error_count"],
            "token_usage_reported_by_provider": trace_end["has_token_usage"],
            "trace_dir": str(traces_dir),
        },
        "seed_manifest": manifest,
    }
    (output_root / "real_full_generation_report.json").write_text(to_json_text(report), encoding="utf-8")
    (output_root / "real_full_generation_report.md").write_text(render_report(report), encoding="utf-8")
    print(json.dumps({
        "project_id": project_id,
        "output_root": str(output_root),
        "chapters": generated["task_count"],
        "passed": generated["passed_count"],
        "atom_usage_records": len(usage_records),
        "distinct_atoms": len({item.get("atom_id") for item in usage_records}),
        "findings": len(findings),
        "llm_calls": report["llm_usage"]["call_count"],
        "total_tokens": report["llm_usage"]["total_tokens"],
        "estimated_total_tokens": report["llm_usage"]["estimated_total_tokens"],
    }, ensure_ascii=False, indent=2), flush=True)


def _atom_usage_details(pipeline, records: list[dict]) -> list[dict[str, Any]]:
    atoms = {item.id: item for item in pipeline.reference_library.list_atoms()}
    counts: dict[str, int] = {}
    last: dict[str, dict] = {}
    for record in records:
        atom_id = record.get("atom_id")
        counts[atom_id] = counts.get(atom_id, 0) + 1
        last[atom_id] = record
    result = []
    for atom_id, count in sorted(counts.items(), key=lambda item: (-item[1], item[0])):
        atom = atoms.get(atom_id)
        result.append({
            "atom_id": atom_id,
            "use_count": count,
            "title_path": atom.title_path if atom else [],
            "engineering_object": atom.engineering_object if atom else "",
            "work_item": atom.work_item if atom else "",
            "process": atom.process if atom else "",
            "content_functions": atom.content_functions if atom else [],
            "match_reason_sample": last[atom_id].get("match_reason", ""),
            "retrieval_score_sample": last[atom_id].get("retrieval_score"),
        })
    return result


def render_report(report: dict[str, Any]) -> str:
    generation = report["generation"]
    usage = report["llm_usage"]
    review = report["compliance_review"]
    lines = [
        "# 水电真实全量生成验证报告",
        "",
        f"- 项目：`{report['project_id']}`",
        f"- 模型：`{report['model']}`（真实 API）",
        f"- 生成范围：{generation.get('generation_scope')}，章节任务 {generation.get('task_count')}，通过 {generation.get('passed_count')}，失败 {len(generation.get('failed') or [])}",
        f"- 成稿字数：目标 {generation.get('target_word_count_total')}，实际 {generation.get('actual_word_count_total')}",
        f"- 生成耗时：{report['timing']['generation_seconds']} 秒；审查耗时：{report['timing']['review_seconds']} 秒",
        "",
        "## 原子要素实际使用",
        f"共记录 {report['reference_atom_usage']['record_count']} 次使用，涉及 {report['reference_atom_usage']['distinct_atom_count']} 条已发布原子。",
        "",
    ]
    for item in report["reference_atom_usage"]["by_atom"]:
        lines.append(f"- `{item['atom_id']}`：使用 {item['use_count']} 次；{item['work_item']} / {item['process']}；功能：{'、'.join(item['content_functions'])}")
        lines.append(f"  匹配理由：{item['match_reason_sample']}")
    lines.extend([
        "",
        "## 规范匹配与违背结果",
        f"匹配条例候选 {review['constraint_match_count']} 条，审查发现 {review['finding_count']} 条，开放问题 {review['open_count']} 条。",
        "",
    ])
    for item in review["constraint_matches"]:
        lines.append(f"- `{item['atom_id']}`：{item['standard_name']} 第 {item['clause_no'] or '-'} 条；得分 {item['score']:.3f}；{item['match_reason']}")
    if review["findings"]:
        lines.extend(["", "### 明确违背或需确认"])
        for item in review["findings"]:
            lines.append(f"- `{item.get('atom_id')}` / 章节 `{item.get('chapter_title')}`：{item.get('status')}；{item.get('explanation')}")
            if item.get("evidence_quote"):
                lines.append(f"  证据：{item['evidence_quote']}")
    else:
        lines.append("本次审查没有返回明确违背条例；这不等于整体合规，仍需人工核对未覆盖条款和项目现场事实。")
    lines.extend([
        "",
        "## 模型消耗",
        f"- API 调用：{usage['call_count']} 次（错误 {usage['error_count']} 次）",
        f"- 供应商返回 token：输入 {usage['prompt_tokens']}，输出 {usage['completion_tokens']}，合计 {usage['total_tokens']}",
        f"- 字符估算 token：{usage['estimated_total_tokens']}（仅当供应商 usage 缺失时参考）",
        f"- 输入字符：{usage['prompt_char_total']}；输出字符：{usage['response_char_total']}",
        f"- API 累计耗时：{usage['elapsed_seconds_total']} 秒",
        f"- 原始 trace：`{usage['trace_dir']}`",
        "",
        "## 产物",
        f"- 最终成稿：`{generation.get('local_final_copy')}`",
        f"- 结构化报告：`{Path(report['output_root']) / 'real_full_generation_report.json'}`",
        f"- 本报告：`{Path(report['output_root']) / 'real_full_generation_report.md'}`",
    ])
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
