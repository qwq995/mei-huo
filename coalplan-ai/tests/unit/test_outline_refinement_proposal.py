from __future__ import annotations

import unittest

from coalplan.application.run_generation_pipeline import _outline_refine_patches
from coalplan.application.workspace_store import _outline_readiness


class OutlineRefinementProposalTest(unittest.TestCase):
    def setUp(self) -> None:
        self.nodes = [
            {"node_id": "root", "title": "施工组织设计", "level": 1, "parent_id": None, "enabled": True},
            {"node_id": "drain", "title": "截排水与监测", "level": 2, "parent_id": "root", "enabled": True},
            {"node_id": "monitor", "title": "边坡监测", "level": 3, "parent_id": "drain", "enabled": True, "auto_fill": ["现状"]},
        ]

    def test_only_returns_real_scoped_changes(self) -> None:
        patches, summary = _outline_refine_patches(
            {"changes": [
                {"action": "update", "node_id": "monitor", "auto_fill": ["监测点布置", "数据反馈"], "reason": "补足闭环"},
                {"action": "update", "node_id": "root", "title": "不应修改一级目录"},
                {"action": "update", "node_id": "drain", "title": "截排水与监测"},
            ]},
            self.nodes,
            scope_node_id="drain",
            scope_mode="subtree",
            preserve_top_level=True,
            max_changes=20,
        )

        self.assertEqual(["monitor"], [item["node_id"] for item in patches])
        self.assertEqual("update", patches[0]["__action"])
        self.assertEqual(1, summary["total"])

    def test_server_assigns_id_for_created_child(self) -> None:
        patches, summary = _outline_refine_patches(
            {"changes": [{"action": "create", "parent_id": "drain", "title": "异常处置与复核", "reason": "形成响应闭环"}]},
            self.nodes,
            scope_node_id="drain",
            scope_mode="subtree",
            preserve_top_level=True,
            max_changes=20,
        )

        self.assertEqual(1, summary["create_count"])
        self.assertTrue(patches[0]["node_id"].startswith("outline_ai_"))
        self.assertEqual("drain", patches[0]["parent_id"])

    def test_readiness_explains_why_a_node_is_not_ready(self) -> None:
        readiness, reasons = _outline_readiness({
            "enabled": True,
            "source_hints": [],
            "chapter_summary": {"coverage_status": "mapping_required", "missing_information": ["施工图"]},
            "manual_fill": ["审批记录"],
        })

        self.assertEqual("needs_confirmation", readiness)
        self.assertTrue(any("投标来源" in reason for reason in reasons))
        self.assertTrue(any("待补资料" in reason for reason in reasons))


if __name__ == "__main__":
    unittest.main()
