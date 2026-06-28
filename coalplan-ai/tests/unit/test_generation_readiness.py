from __future__ import annotations

import unittest

from coalplan.application.generation_readiness import build_generation_readiness_report
from coalplan.domain.generation import ChapterTask, GenerationRun, Project, SourceMatch
from coalplan.domain.generation_control import ChapterGenerationPolicy, GenerationControlPlan, RevisionTrigger
from coalplan.domain.outline import SourceMappingResult
from coalplan.domain.templates import TemplateNode, TemplateTree


class GenerationReadinessTest(unittest.TestCase):
    def test_report_classifies_outline_nodes_before_generation(self) -> None:
        split_node = TemplateNode(
            id="node_craft",
            title="Drilling and Grouting",
            level=1,
            source_rules=["drilling"],
            auto_fill=["process"],
            manual_fill=["parameters"],
        )
        child = TemplateNode(id="node_child", title="Water Injection Flow", level=2, source_rules=["water"], auto_fill=["flow"], manual_fill=["pressure"])
        parent = TemplateNode(id="node_parent", title="Water Injection Works", level=1, children=[child])
        ready_node = TemplateNode(id="node_ready", title="Project Overview", level=1, source_rules=["overview"], auto_fill=["scope"])
        no_source_node = TemplateNode(id="node_no_source", title="Approval Procedures", level=1, source_rules=["approval"], manual_fill=["approval file"])
        done_node = TemplateNode(id="node_done", title="Quality Target", level=1, source_rules=["quality"], auto_fill=["target"])
        tree = TemplateTree(id="tpl", name="Demo", nodes=[split_node, parent, ready_node, no_source_node, done_node])
        project = Project(name="demo", template_id="tpl", template_tree=tree)
        run = GenerationRun(project_name=project.name, template_id=project.template_id)
        run.chapter_tasks.extend(
            [
                ChapterTask(
                    node_id="node_ready",
                    title="Project Overview",
                    source_mapping=SourceMappingResult(
                        node_id="node_ready",
                        matches=[{"section_id": "sec_scope", "title_path": ["Bid", "Overview"], "confidence": 0.9}],
                    ),
                    source_matches=[SourceMatch(section_id="sec_scope", title_path=["Bid", "Overview"], snippet="scope", score=0.9)],
                ),
                ChapterTask(
                    node_id="node_no_source",
                    title="Approval Procedures",
                    source_mapping=SourceMappingResult(node_id="node_no_source", matches=[], missing_evidence=["approval file"]),
                ),
                ChapterTask(
                    node_id="node_done",
                    title="Quality Target",
                    status="passed",
                    draft_id="draft_1",
                    source_mapping=SourceMappingResult(
                        node_id="node_done",
                        matches=[{"section_id": "sec_quality", "title_path": ["Bid", "Quality"], "confidence": 0.9}],
                    ),
                    source_matches=[SourceMatch(section_id="sec_quality", title_path=["Bid", "Quality"], snippet="qualified", score=0.9)],
                ),
            ]
        )
        project.runs.append(run)
        control = GenerationControlPlan(
            project_id=project.id,
            chapter_policies=[
                ChapterGenerationPolicy(node_id="node_craft", title="Drilling and Grouting", split_required=True),
                ChapterGenerationPolicy(node_id="node_ready", title="Project Overview", target_word_count=600),
            ],
        )

        report = build_generation_readiness_report(
            project=project,
            template_tree=tree,
            control_plan=control,
            workspace_store=_Workspace({"node_done": "ver_1"}),
        )
        by_node = {item.node_id: item for item in report.nodes}

        self.assertEqual("waiting_for_user", report.status)
        self.assertEqual("split_required", by_node["node_craft"].status)
        self.assertEqual("has_children", by_node["node_parent"].status)
        self.assertEqual("needs_mapping", by_node["node_child"].status)
        self.assertEqual("ready_to_generate", by_node["node_ready"].status)
        self.assertEqual("needs_human_input", by_node["node_no_source"].status)
        self.assertEqual("ready_for_merge", by_node["node_done"].status)
        self.assertEqual(1, report.metrics["split_required"])
        self.assertEqual(1, report.metrics["needs_human_input"])
        self.assertEqual(1, report.metrics["ready_for_merge"])
        self.assertEqual(3, report.metrics["auto_runnable"])
        batches = {batch.group_id: batch for batch in report.batches}
        self.assertEqual({"node_parent", "node_child", "node_ready"}, {item.node_id for item in batches["auto_generation"].items})
        self.assertEqual({"node_craft", "node_no_source"}, {item.node_id for item in batches["user_confirmation"].items})
        self.assertEqual(["node_done"], [item.node_id for item in batches["merge_review"].items])

    def test_revision_decision_overrides_selected_passed_version(self) -> None:
        node = TemplateNode(id="node_quality", title="Quality Measures", level=1, source_rules=["quality"], auto_fill=["measures"])
        tree = TemplateTree(id="tpl", name="Demo", nodes=[node])
        project = Project(name="demo", template_id="tpl", template_tree=tree)
        run = GenerationRun(project_name=project.name, template_id=project.template_id)
        run.chapter_tasks.append(
            ChapterTask(
                node_id=node.id,
                title=node.title,
                status="passed",
                draft_id="draft_1",
                source_mapping=SourceMappingResult(
                    node_id=node.id,
                    matches=[{"section_id": "sec_quality", "title_path": ["Bid", "Quality"], "confidence": 0.9}],
                ),
                source_matches=[SourceMatch(section_id="sec_quality", title_path=["Bid", "Quality"], snippet="inspection", score=0.9)],
            )
        )
        project.runs.append(run)

        report = build_generation_readiness_report(
            project=project,
            template_tree=tree,
            revision_decisions=[
                {
                    "node_id": node.id,
                    "title": node.title,
                    "decision": "regenerate",
                    "severity": "warning",
                    "reasons": ["omitted_required_source_facts"],
                    "required_changes": ["Absorb evidence_id ev_1 before merge."],
                }
            ],
            workspace_store=_Workspace({node.id: "ver_1"}),
        )
        item = report.nodes[0]

        self.assertEqual("revision_required", report.status)
        self.assertEqual("needs_revision", item.status)
        self.assertEqual("regenerate", item.next_action)
        self.assertEqual("regenerate", item.revision_decision)
        self.assertEqual("warning", item.revision_severity)
        self.assertIn("omitted_required_source_facts", item.reason)
        self.assertEqual(0, report.metrics["ready_for_merge"])
        self.assertEqual(1, report.metrics["auto_runnable"])
        batches = {batch.group_id: batch for batch in report.batches}
        self.assertEqual(["node_quality"], [batch_item.node_id for batch_item in batches["auto_revision"].items])

    def test_control_plan_revision_trigger_marks_existing_versions_only(self) -> None:
        done = TemplateNode(id="node_done", title="Generated Chapter", level=1, source_rules=["done"], auto_fill=["rewrite"])
        pending = TemplateNode(id="node_pending", title="Pending Chapter", level=1, source_rules=["pending"], auto_fill=["write"])
        tree = TemplateTree(id="tpl", name="Demo", nodes=[done, pending])
        project = Project(name="demo", template_id="tpl", template_tree=tree)
        run = GenerationRun(project_name=project.name, template_id=project.template_id)
        run.chapter_tasks.append(
            ChapterTask(
                node_id=done.id,
                title=done.title,
                status="passed",
                draft_id="draft_done",
                source_mapping=SourceMappingResult(
                    node_id=done.id,
                    matches=[{"section_id": "sec_done", "title_path": ["Bid", "Done"], "confidence": 0.9}],
                ),
                source_matches=[SourceMatch(section_id="sec_done", title_path=["Bid", "Done"], snippet="fact", score=0.9)],
            )
        )
        project.runs.append(run)
        control = GenerationControlPlan(
            project_id=project.id,
            revision_triggers=[
                RevisionTrigger(
                    node_id="all_chapters",
                    title="detail budget",
                    action="regenerate",
                    severity="warning",
                    reason="Generated document is too short for the reference.",
                    evidence=["Increase detail for existing generated chapters."],
                )
            ],
        )

        report = build_generation_readiness_report(
            project=project,
            template_tree=tree,
            control_plan=control,
            workspace_store=_Workspace({done.id: "ver_done"}),
        )
        by_node = {item.node_id: item for item in report.nodes}

        self.assertEqual("needs_revision", by_node[done.id].status)
        self.assertEqual("regenerate", by_node[done.id].next_action)
        self.assertIn("too short", by_node[done.id].reason)
        self.assertEqual("needs_mapping", by_node[pending.id].status)
        batches = {batch.group_id: batch for batch in report.batches}
        self.assertEqual([done.id], [item.node_id for item in batches["auto_revision"].items])
        self.assertIn(pending.id, [item.node_id for item in batches["auto_generation"].items])

    def test_generation_metadata_target_blocks_ready_for_merge(self) -> None:
        node = TemplateNode(id="node_craft", title="Craft Chapter", level=1, source_rules=["craft"], auto_fill=["method"])
        tree = TemplateTree(id="tpl", name="Demo", nodes=[node])
        project = Project(name="demo", template_id="tpl", template_tree=tree)
        run = GenerationRun(project_name=project.name, template_id=project.template_id)
        run.chapter_tasks.append(
            ChapterTask(
                node_id=node.id,
                title=node.title,
                status="passed",
                draft_id="draft_1",
                source_mapping=SourceMappingResult(
                    node_id=node.id,
                    matches=[{"section_id": "sec_craft", "title_path": ["Bid", "Craft"], "confidence": 0.9}],
                ),
                source_matches=[SourceMatch(section_id="sec_craft", title_path=["Bid", "Craft"], snippet="method", score=0.9)],
            )
        )
        project.runs.append(run)

        report = build_generation_readiness_report(
            project=project,
            template_tree=tree,
            generation_metadata_targets=[
                {
                    "node_id": node.id,
                    "version_id": "ver_1",
                    "title": node.title,
                    "action": "regenerate",
                    "reason": "Primary local writing-pattern prompt card was omitted.",
                    "next_actions": ["Regenerate with process controls and acceptance evidence."],
                    "prompt_card_audits": [
                        {
                            "pattern_key": "craft",
                            "suggested_action": "regenerate",
                            "coverage_ratio": 0.1,
                            "missing_requirements": ["Write process controls"],
                        }
                    ],
                }
            ],
            workspace_store=_Workspace({node.id: "ver_1"}),
        )
        item = report.nodes[0]

        self.assertEqual("revision_required", report.status)
        self.assertEqual("needs_revision", item.status)
        self.assertEqual("regenerate", item.next_action)
        self.assertEqual("regenerate", item.revision_decision)
        self.assertIn("Primary local writing-pattern", item.reason)
        self.assertEqual(0, report.metrics["ready_for_merge"])
        batches = {batch.group_id: batch for batch in report.batches}
        self.assertEqual([node.id], [batch_item.node_id for batch_item in batches["auto_revision"].items])


class _Workspace:
    def __init__(self, selected_by_node: dict[str, str]) -> None:
        self.selected_by_node = selected_by_node

    def get_workspace(self, _project_id: str, node_id: str) -> dict:
        return {"selected_version_id": self.selected_by_node.get(node_id)}


if __name__ == "__main__":
    unittest.main()
