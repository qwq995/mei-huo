"""Small live-model workflow against an isolated copy of real bid excerpts."""
import argparse
import json
import sqlite3
from pathlib import Path
from threading import local

from coalplan.application.outline_planning import OutlinePlanningService
from coalplan.application.run_generation_pipeline import GenerationPipeline
from coalplan.application.workspace_store import WorkspaceStore
from coalplan.domain.generation import Project
from coalplan.domain.documents import MarkdownSection
from coalplan.infrastructure.database.repository import DatabaseProjectRepository
from coalplan.infrastructure.database.session import create_session_factory, init_database, sqlite_url_for_storage
from coalplan.infrastructure.llm.openai_compatible import OpenAICompatibleLLMClient
from coalplan.infrastructure.markdown.parser import MarkdownDocumentParser
from coalplan.infrastructure.retrieval.keyword_retriever import KeywordSourceRetriever
from coalplan.infrastructure.storage.local_artifact_repository import LocalArtifactRepository
from coalplan.infrastructure.templates.markdown_template_loader import MarkdownTemplateLoader
from coalplan.settings import Settings
from coalplan.infrastructure.llm.codex_cli import CodexCliStructuredLLMClient


class PlanningCodexClient(CodexCliStructuredLLMClient):
    _metrics = local()

    def _write_trace(self, schema_name, prompt, response, elapsed_seconds, error, usage):
        self._metrics.usage = usage
        super()._write_trace(schema_name, prompt, response, elapsed_seconds, error, usage)

    @property
    def last_usage(self):
        return getattr(self._metrics, "usage", None)

    def complete_json(self, prompt, schema_name):
        result = super().complete_json(prompt + "\n将任务结果JSON序列化为字符串，放入result_json字段。", schema_name="OutlinePlanning")
        return json.loads(result["result_json"])


class MeasuredClient(OpenAICompatibleLLMClient):
    _metrics = local()

    def _post_chat_completions(self, payload):
        result = super()._post_chat_completions(payload)
        self._metrics.usage = result.get("usage")
        return result

    @property
    def last_usage(self):
        return getattr(self._metrics, "usage", None)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-project", default="project_0b88316fba28")
    parser.add_argument("--output", type=Path, default=Path(".coalplan-data/planning-validation"))
    parser.add_argument("--resume-project")
    parser.add_argument("--provider", choices=["deepseek", "codex"], default="deepseek")
    parser.add_argument("--report-only", action="store_true")
    args = parser.parse_args()
    settings = Settings()
    args.output.mkdir(parents=True, exist_ok=True)
    factory = create_session_factory(sqlite_url_for_storage(args.output))
    init_database(factory)
    artifacts = LocalArtifactRepository(args.output / "artifacts")
    projects = DatabaseProjectRepository(factory)
    if args.resume_project:
        project = projects.get(args.resume_project)
    else:
        with sqlite3.connect("file:.coalplan-data/coalplan.db?mode=ro", uri=True) as connection:
            row = connection.execute("SELECT state_json FROM projects WHERE id=?", (args.source_project,)).fetchone()
        source = Project.model_validate_json(row[0])
        sections, budget = [], 0
        for section in source.sections:
            if not section.title_path or "技术文件" not in section.title_path[0] or len(section.content) < 150:
                continue
            if budget + len(section.content) > 14000:
                continue
            sections.append(section)
            budget += len(section.content)
            if len(sections) >= 6:
                break
        if not sections:
            raise ValueError("没有找到技术文件正文样本")
        project = projects.save(Project(name=source.name + "（规划验证副本）", template_id=source.template_id, sections=sections))
    llm = MeasuredClient(base_url=settings.deepseek_base_url, api_key=settings.deepseek_api_key, model=settings.deepseek_model, disable_thinking=True, timeout=180, trace_dir=args.output / "traces")
    if args.provider == "codex":
        llm = PlanningCodexClient(model="gpt-5.6-sol", schema_dir=Path("config/outline_planning").resolve(), workdir=Path.cwd(), trace_dir=args.output / "codex-traces", timeout=300)
    store = WorkspaceStore(factory, artifacts)
    pipeline = GenerationPipeline(projects=projects, artifacts=artifacts, parser=MarkdownDocumentParser(), templates=MarkdownTemplateLoader(Path("src/coalplan/assets/templates")), retriever=KeywordSourceRetriever(), llm=llm, structured_llm=llm, workspace_store=store)
    service = OutlinePlanningService(pipeline)
    def execute(action, **payload):
        print("ACTION", action, flush=True)
        return service.execute(project.id, action, payload, lambda *event: print(event, flush=True))
    def confirm():
        state = service.get(project.id)
        return service.confirm(project.id, {"revision": state["revision"], "stage": state["stage"], "outline_fingerprint": state["outline_fingerprint"]})
    print("PROJECT", project.id, flush=True)
    try:
        if args.report_only:
            return
        state = service.get(project.id)
        if state["stage"] == "understanding":
            execute("understand")
            confirm()
        state = service.get(project.id)
        if state["stage"] == "skeleton":
            chosen = state["understanding"]["recommendations"][0]["template_id"]
            proposal = execute("skeleton", template_id=chosen)
            store.apply_proposal(project.id, proposal["id"])
            confirm()
        state = service.get(project.id)
        if state["stage"] == "expansion":
            roots = store.list_outline_nodes(project.id)
            root = next(n for n in roots if n["chapter_summary"].get("semantic_module") == "technology")
            proposal = execute("expand", node_id=root["node_id"])
            store.apply_proposal(project.id, proposal["id"])
            proposal = execute("chat", suggestion="把隧洞排水相关内容写清楚：工艺部分说明排水方法，设备投入放到资源计划，不要在两处重复。只调整已有节点的写作任务，保留标题。")
            store.apply_proposal(project.id, proposal["id"])
            confirm()
        if service.get(project.id)["stage"] == "blueprint":
            execute("blueprint", parallelism=4)
            confirm()
        state = service.get(project.id)
        contract = next(c for c in state["blueprint"]["contracts"] if c["role"] == "independent" and c["source_section_ids"])
        section_map = {s.id: s for s in project.sections}
        preview = llm.complete("依据以下已确认章节生成指导与真实项目来源，生成400字以内施工组织设计正文。任务与技巧分别遵守，不编造缺失值，不显示系统标注。缺失资料已由系统另存缺口台账，正文必须完全省略未知信息及待补资料章节，不写待补充、需提供、缺失项或任何人工占位。只描述有来源支持的项目事实。\n" + json.dumps({"blueprint": state["blueprint"]["summary"], "contract": contract, "sources": [section_map[s].model_dump() for s in contract["source_section_ids"]]}, ensure_ascii=False))
        artifacts.write_text(project.id, "outline/planning/preview.md", preview)
    finally:
        state = service.get(project.id)
        calls = state.get("calls", [])
        metrics = {"project_id": project.id, "stage": state["stage"], "planning_calls": len(calls), "planning_input_tokens": sum((c.get("usage") or {}).get("prompt_tokens", 0) for c in calls), "planning_output_tokens": sum((c.get("usage") or {}).get("completion_tokens", 0) for c in calls), "state": {k: v for k, v in state.items() if k != "cache"}}
        if args.provider == "codex":
            traces = [json.loads(p.read_text(encoding="utf-8")) for p in (args.output / "codex-traces").glob("*.json")]
            planning = [t for t in traces if t.get("schema_name") == "OutlinePlanning"]
            metrics.update(planning_input_tokens=sum((t.get("usage") or {}).get("input_tokens", 0) for t in planning), planning_output_tokens=sum((t.get("usage") or {}).get("output_tokens", 0) for t in planning), all_model_calls=len(traces), all_input_tokens=sum((t.get("usage") or {}).get("input_tokens", 0) for t in traces), all_output_tokens=sum((t.get("usage") or {}).get("output_tokens", 0) for t in traces), cached_input_tokens=sum((t.get("usage") or {}).get("cached_input_tokens", 0) for t in traces), summed_request_seconds=round(sum(t.get("elapsed_seconds", 0) for t in traces), 2), provider="codex-cli", cost_currency=None, note="Token counts include Codex runtime context; no monetary billing estimate is available. Trace totals include prior preview attempts in this isolated directory.")
        artifacts.write_text(project.id, "outline/planning/validation.json", json.dumps(metrics, ensure_ascii=False, indent=2))
        print(json.dumps({k: v for k, v in metrics.items() if k != "state"}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
