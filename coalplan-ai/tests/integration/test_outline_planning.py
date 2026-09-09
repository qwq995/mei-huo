import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from coalplan.application.outline_planning import OutlinePlanningService, NodeContract, rules, validate_structure, validate_contracts, assert_planning_generation_ready
from coalplan.application.workspace_store import WorkspaceStore
from coalplan.domain.documents import MarkdownSection
from coalplan.domain.generation import Project
from coalplan.domain.templates import TemplateTree, TemplateNode
from coalplan.infrastructure.database.repository import DatabaseProjectRepository
from coalplan.infrastructure.database.session import create_session_factory, init_database, sqlite_url_for_storage
from coalplan.infrastructure.storage.local_artifact_repository import LocalArtifactRepository


class PlanningLLM:
    def __init__(self):
        self.calls = []

    def complete(self, prompt):
        self.calls.append("summary")
        return "本章按子章职责统筹组织。"

    def complete_json(self, prompt, schema_name):
        request = json.loads(prompt.split("\n", 1)[1])
        stage, data = request["stage"], request["input"]
        self.calls.append(stage)
        if stage == "extract_project":
            return {"facts": [{"statement": "隧道含排水", "section_ids": ["s1"]}], "scope": ["隧道"], "processes": ["排水"], "requirements": []}
        if stage == "understand_and_recommend":
            return {"overview": "县道复建含隧道及排水工程", "sector": "road", "scope": ["隧道"], "processes": ["排水"], "requirements": [], "conflicts": [], "unknowns": [], "recommendations": [{"template_id": "test", "reason": "适用于公路", "differences": []}]}
        if stage == "top_level_skeleton":
            return {"nodes": [{"title": r["title"], "module": r["module"], "requirement_ids": [r["id"]]} for r in data["requirements"]]}
        if stage == "second_level":
            return {"nodes": [{"node_id": "drain", "parent_id": data["root"]["node_id"], "title": "隧道排水", "level": 2, "source_hints": ["s1"], "auto_fill": ["排水方法"], "chapter_summary": {"overview": "隧道排水方法"}}]}
        if stage == "whole_book_ownership":
            return {"summary": "工艺详述，保障章引用", "topics": []}
        if stage == "chapter_contracts":
            return {"contracts": [{"node_id": n["node_id"], "scope_statement": n["title"], "writing_tasks": ["本章内容"], "writing_skills": ["按照条件、措施、检查组织"], "source_section_ids": ["s1"], "role": n.get("chapter_summary", {}).get("planning_role") or "independent"} for n in data["nodes"]]}
        if stage == "basis_registry":
            return {"files": [], "unresolved": []}
        raise AssertionError(stage)


class OutlinePlanningTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        factory = create_session_factory(sqlite_url_for_storage(root))
        init_database(factory)
        artifacts = LocalArtifactRepository(root / "artifacts")
        projects = DatabaseProjectRepository(factory)
        self.project = projects.save(Project(name="县道项目", template_id="test", sections=[MarkdownSection(id="s1", title_path=["工程概况"], level=1, content="县道复建工程包含隧道开挖和施工排水。", source_file="投标.md", start_line=1, end_line=2)]))
        self.store = WorkspaceStore(factory, artifacts)
        tree = TemplateTree(id="test", name="公路施组", nodes=[TemplateNode(id="root", title="工程概况", level=1)])
        self.llm = PlanningLLM()
        self.pipeline = SimpleNamespace(projects=projects, workspace_store=self.store, artifacts=artifacts, reference_library=None, templates=SimpleNamespace(list_templates=lambda: [{"template_id": "test"}], load=lambda _: tree), _structured_llm=lambda: self.llm)
        self.service = OutlinePlanningService(self.pipeline)

    def execute(self, action, **payload):
        return self.service.execute(self.project.id, action, payload, lambda *_: None)

    def confirm(self):
        state = self.service.get(self.project.id)
        return self.service.confirm(self.project.id, {"revision": state["revision"], "stage": state["stage"], "outline_fingerprint": state["outline_fingerprint"]})

    def skeleton(self):
        self.execute("understand")
        self.confirm()
        proposal = self.execute("skeleton", template_id="test")
        self.store.apply_proposal(self.project.id, proposal["id"])
        return proposal

    def ready(self):
        self.skeleton()
        self.confirm()
        self.confirm()
        self.execute("blueprint", parallelism=2)
        self.confirm()

    def test_complete_flow_persists_and_attaches_contracts(self):
        self.skeleton()
        self.confirm()
        root = next(n for n in self.store.list_outline_nodes(self.project.id) if n["chapter_summary"].get("semantic_module") == "technology")
        proposal = self.execute("expand", node_id=root["node_id"])
        self.store.apply_proposal(self.project.id, proposal["id"])
        self.confirm()
        self.execute("blueprint", parallelism=2)
        self.confirm()
        restored = OutlinePlanningService(self.pipeline).get(self.project.id)
        self.assertEqual("ready", restored["stage"])
        self.assertFalse(restored["stale_node_ids"])
        node = next(n for n in self.store.list_outline_nodes(self.project.id) if n["node_id"] == "drain")
        self.assertEqual(["本章内容"], [i["title"] for i in node["chapter_summary"]["generation_plan"]["items"]])
        self.assertEqual(["按照条件、措施、检查组织"], node["chapter_summary"]["generation_plan"]["writing_skills"])

    def test_missing_required_content_prevents_partial_apply(self):
        self.execute("understand")
        self.confirm()
        proposal = self.execute("skeleton", template_id="test")
        excluded = proposal["preview"]["nodes"][0]["node_id"]
        with self.assertRaisesRegex(ValueError, "必需内容"):
            self.store.apply_proposal(self.project.id, proposal["id"], exclude_node_ids=[excluded])
        self.assertFalse(self.store.list_outline_nodes(self.project.id))

    def test_user_contract_survives_regeneration(self):
        self.ready()
        state = self.service.get(self.project.id)
        contract = state["blueprint"]["contracts"][0]
        contract["writing_tasks"] = ["用户指定的任务"]
        self.service.edit_contract(self.project.id, contract["node_id"], {"revision": state["revision"], "contract": contract})
        self.execute("blueprint")
        state = self.service.get(self.project.id)
        self.assertEqual(["用户指定的任务"], next(c for c in state["blueprint"]["contracts"] if c["node_id"] == contract["node_id"])["writing_tasks"])

    def test_changed_source_invalidates_mapped_contract(self):
        self.ready()
        project = self.pipeline.projects.get(self.project.id)
        project.sections[0].content += "新增排水要求"
        self.pipeline.projects.save(project)
        state = self.service.get(self.project.id)
        self.assertTrue(state["stale_node_ids"])
        with self.assertRaises(ValueError):
            assert_planning_generation_ready(self.pipeline, self.project.id, state["stale_node_ids"][0])

    def test_basis_waits_for_selected_versions_and_creates_candidate(self):
        self.ready()
        with self.assertRaisesRegex(ValueError, "选用正文"):
            self.execute("basis")
        nodes = self.store.list_outline_nodes(self.project.id)
        for n in nodes:
            role = n["chapter_summary"]["generation_plan"]["generation_role"]
            if role not in {"deferred_basis", "external_attachment"}:
                self.store.create_chapter_version(self.project.id, n["node_id"], title=n["title"], markdown="已完成正文", source_type="user", source_section_ids=["s1"])
        result = self.execute("basis")
        self.assertEqual(1, len(result["files"]))
        self.assertEqual("投标.md", result["files"][0]["file_name"])
        basis_node = next(n for n in self.store.list_outline_nodes(self.project.id) if n["chapter_summary"].get("planning_role") == "deferred_basis")
        self.assertIsNone(basis_node["selected_version_id"])

    def test_retry_uses_successful_batch_cache(self):
        self.execute("understand")
        count = len(self.llm.calls)
        self.execute("understand")
        self.assertEqual(count, len(self.llm.calls))

    def test_summary_uses_selected_children_and_prompt_cache(self):
        self.ready()
        state = self.service.get(self.project.id)
        contracts = [c for c in state["blueprint"]["contracts"] if c["role"] == "independent"]
        parent, child = contracts[:2]
        parent.update(role="summary", dependencies=[child["node_id"]])
        self.service.save(self.project.id, state)
        with self.assertRaisesRegex(ValueError, "选用子章"):
            self.service.summary_draft(self.project.id, parent["node_id"])
        version = self.store.create_chapter_version(self.project.id, child["node_id"], title="子章", markdown="已选用的子章正文", source_type="user", source_section_ids=["s1"])
        first = self.service.summary_draft(self.project.id, parent["node_id"])
        second = self.service.summary_draft(self.project.id, parent["node_id"])
        self.assertEqual(first.markdown, second.markdown)
        self.assertEqual(1, self.llm.calls.count("summary"))
        self.assertEqual(version["id"], first.generation_metadata["child_versions"][0]["version_id"])

    def test_blueprint_roles_control_normal_generation_tasks(self):
        for role in ("summary", "independent", "deferred_basis", "external_attachment"):
            node = TemplateNode(id="x", title="测试", level=1, auto_fill=["内容"], chapter_summary={"generation_plan": {"blueprint_version": 1, "generation_role": role}})
            self.assertEqual(role in {"summary", "independent"}, node.has_generation_contract)

    def test_stale_revision_cannot_overwrite_planning(self):
        original = self.service.get(self.project.id)
        self.service.save(self.project.id, original)
        with self.assertRaises(ValueError):
            self.service.save(self.project.id, original)

    def test_cycles_are_rejected(self):
        nodes = [{"node_id": "a", "parent_id": "b", "level": 2, "title": "a"}, {"node_id": "b", "parent_id": "a", "level": 1, "title": "b"}]
        with self.assertRaises(ValueError):
            validate_structure(nodes, [])
        contracts = [NodeContract(node_id="a", scope_statement="a", writing_tasks=["a"], dependencies=["b"]), NodeContract(node_id="b", scope_statement="b", writing_tasks=["b"], dependencies=["a"])]
        with self.assertRaisesRegex(ValueError, "循环"):
            validate_contracts(contracts, nodes, set())


if __name__ == "__main__":
    unittest.main()
