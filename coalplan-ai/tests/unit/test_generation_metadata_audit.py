from __future__ import annotations

import unittest

from coalplan.application.generation_metadata_audit import audit_version_generation_metadata
from coalplan.application.run_generation_pipeline import (
    _generation_metadata_cue_subsection_nodes,
    _generation_metadata_revision_action,
    _render_generation_metadata_revision_context,
)
from coalplan.domain.templates import TemplateNode


class GenerationMetadataAuditTest(unittest.TestCase):
    def test_missing_metadata_returns_warning(self) -> None:
        audit = audit_version_generation_metadata({"id": "ver_1", "markdown": "# 章节\n"})

        self.assertEqual("warning", audit["status"])
        self.assertEqual(1, audit["metrics"]["missing_metadata"])
        self.assertIn("not traceable", audit["issues"][0])

    def test_metadata_audit_returns_pattern_details(self) -> None:
        version = {
            "id": "ver_1",
            "markdown": "# 工程概况\n\n## 生成正文\n项目名称、工程范围、主要工程量、施工条件、工期目标、质量目标、安全目标、环保目标均依据来源整理。\n",
            "generation_metadata": {
                "selected_pattern_keys": ["overview"],
                "pattern_evidence_scope": "structural guidance only",
            },
        }

        audit = audit_version_generation_metadata(version)

        self.assertIn(audit["status"], {"passed", "warning"})
        self.assertEqual(1, audit["metrics"]["selected_pattern_count"])
        self.assertEqual(1, audit["metrics"]["audited_pattern_count"])
        self.assertEqual("overview", audit["pattern_audits"][0]["pattern_key"])

    def test_prompt_card_requirements_are_audited_and_sent_to_revision_context(self) -> None:
        version = {
            "id": "ver_2",
            "markdown": "# craft\n\n## 生成正文\n\nThis chapter only says generic construction text.\n",
            "generation_metadata": {
                "selected_pattern_keys": [],
                "generation_policy": {
                    "pattern_prompt_cards": [
                        {
                            "pattern_key": "craft",
                            "generation_moves": [
                                "Write process controls",
                                "Record acceptance evidence",
                            ],
                            "source_mapping_requirements": ["Map process and acceptance evidence."],
                            "human_only_items": ["approved final pressure"],
                            "revision_checks": ["regenerate when process controls are omitted"],
                        }
                    ]
                },
            },
        }

        audit = audit_version_generation_metadata(version)

        self.assertEqual("warning", audit["status"])
        self.assertEqual(1, audit["metrics"]["prompt_card_count"])
        self.assertEqual(1, audit["metrics"]["prompt_card_actionable_count"])
        self.assertEqual("regenerate", audit["prompt_card_audits"][0]["suggested_action"])
        self.assertIn("Write process controls", audit["prompt_card_audits"][0]["missing_requirements"])
        self.assertEqual("regenerate", _generation_metadata_revision_action(audit))
        context = _render_generation_metadata_revision_context(audit)
        self.assertIn("prompt_card_audits", context)
        self.assertIn("Write process controls", context)
        self.assertIn("Map process and acceptance evidence.", context)

    def test_craft_body_cues_trigger_subsection_expansion_action(self) -> None:
        version = {
            "id": "ver_3",
            "markdown": "# 灌浆施工\n\n## 生成正文\n\n本节说明灌浆施工按现场条件组织实施。\n",
            "generation_metadata": {
                "selected_pattern_keys": [],
                "generation_policy": {
                    "pattern_prompt_cards": [
                        {
                            "pattern_key": "craft",
                            "generation_moves": [
                                "按施工准备、测量放样、工艺流程、过程控制、检查验收组织工艺正文",
                                "把人员、设备、材料、作业条件写入工序实施前置条件",
                            ],
                            "detail_design_rules": [
                                "Allocate target word count across process/control/acceptance.",
                            ],
                            "source_mapping_requirements": ["Map process, resources, control, and acceptance evidence."],
                            "human_only_items": ["approved final pressure"],
                            "revision_checks": ["split subsection when craft cues are omitted"],
                        }
                    ]
                },
            },
        }

        audit = audit_version_generation_metadata(version)

        self.assertEqual("warning", audit["status"])
        self.assertEqual("expand_subsections", audit["prompt_card_audits"][0]["suggested_action"])
        self.assertEqual("expand_subsections", _generation_metadata_revision_action(audit))
        self.assertGreaterEqual(audit["metrics"]["requires_llm_count"], 1)
        self.assertGreaterEqual(audit["metrics"]["requires_user_confirmation_count"], 1)
        context = _render_generation_metadata_revision_context(audit)
        self.assertIn("施工准备", context)
        self.assertIn("Split or expand", "\n".join(audit["next_actions"]))


    def test_craft_body_cues_become_source_mappable_subsection_nodes(self) -> None:
        parent = TemplateNode(id="node_grout", title="灌浆施工", level=2, target_word_count=1600)
        audit = {
            "issues": [
                "Pattern prompt card `craft` suggests `expand_subsections`; missing=按施工准备、测量放样、工艺流程、过程控制、检查验收组织工艺正文.",
            ],
            "prompt_card_audits": [
                {
                    "suggested_action": "expand_subsections",
                    "missing_requirements": ["按施工准备、测量放样、工艺流程、过程控制、检查验收组织工艺正文"],
                    "source_mapping_requirements": ["Map process, control, and acceptance evidence."],
                }
            ],
        }

        nodes = _generation_metadata_cue_subsection_nodes(
            parent_node=parent,
            audit=audit,
            existing_titles=set(),
            start_sort_order=10,
        )

        titles = [node["title"] for node in nodes]
        self.assertIn("施工准备与作业条件", titles)
        self.assertIn("工艺流程与施工顺序", titles)
        self.assertIn("过程控制与参数管理", titles)
        self.assertIn("检查验收与资料记录", titles)
        self.assertTrue(all(node["parent_id"] == "node_grout" for node in nodes))
        self.assertTrue(all(node["source_rules"] for node in nodes))
        self.assertTrue(any("Map process" in rule for node in nodes for rule in node["source_rules"]))
        self.assertTrue(all("section_id/evidence_id" in " ".join(node["special_notes"]) for node in nodes))


if __name__ == "__main__":
    unittest.main()
