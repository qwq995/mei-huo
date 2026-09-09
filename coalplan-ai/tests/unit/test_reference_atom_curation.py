from __future__ import annotations

import unittest

from coalplan.application.reference_atom_curation import curate_reference_atoms
from coalplan.application.reference_atom_v2 import finalize_v2_atom
from coalplan.domain.reference_library import AtomParameterSlot, ReferenceAtom


class ReferenceAtomCurationTests(unittest.TestCase):
    def test_duplicates_and_parameter_conflicts_are_related_without_merging_sources(self) -> None:
        left = _atom("left", "炮孔间距控制为0.5m，钻孔完成后检查孔位和孔深。", "0.5m")
        right = _atom("right", "炮孔间距控制为0.6m，钻孔完成后检查孔位和孔深。", "0.6m")
        result = curate_reference_atoms([left, right], duplicate_threshold=0.8)
        self.assertEqual(2, len(result.atoms))
        self.assertEqual(1, len(result.duplicate_groups))
        self.assertEqual(1, len(result.conflicts))
        self.assertTrue(any(item.relation_type == "duplicate_of" for item in left.relations))
        self.assertTrue(any(item.relation_type == "conflicts_with" for item in right.relations))

    def test_generic_project_slots_and_equivalent_numeric_values_do_not_raise_conflicts(self) -> None:
        left = _atom("left", "养护时间不少于 7天。", "不少于 7天")
        right = _atom("right", "养护时间不少于7天。", "不少于7天")
        left.parameter_slots[0].slot_key = "project_specific.1"
        right.parameter_slots[0].slot_key = "project_specific.1"
        self.assertEqual([], curate_reference_atoms([left, right]).conflicts)

        left.parameter_slots[0].slot_key = "curing_duration"
        right.parameter_slots[0].slot_key = "curing_duration"
        self.assertEqual([], curate_reference_atoms([left, right]).conflicts)

    def test_same_parameter_on_different_engineering_objects_is_not_a_conflict(self) -> None:
        left = _atom("left", "炮孔间距为0.5m。", "0.5m")
        right = _atom("right", "排水孔间距为0.6m。", "0.6m")
        right.engineering_object = "排水孔"
        self.assertEqual([], curate_reference_atoms([left, right]).conflicts)

    def test_contained_wording_and_incomparable_standard_forms_do_not_raise_conflicts(self) -> None:
        left = _atom("left", "跟踪精度符合产品的技术要求。", "符合产品的技术要求")
        right = _atom("right", "跟踪精度应符合产品的技术要求。", "应符合产品的技术要求")
        self.assertEqual([], curate_reference_atoms([left, right]).conflicts)

        left.parameter_slots[0].source_value = "《施工现场临时用电安全技术规范》"
        right.parameter_slots[0].source_value = "JGJ 46-2012"
        self.assertEqual([], curate_reference_atoms([left, right]).conflicts)


def _atom(atom_id: str, text: str, value: str) -> ReferenceAtom:
    atom = ReferenceAtom(
        id=atom_id, document_id=f"doc-{atom_id}", project_name=atom_id, project_type="水电/隧洞",
        title_path=["钻孔爆破"], content=text, raw_excerpt=text, start_line=1, end_line=1,
        atom_type="control", chapter_module="process_technology", engineering_system="underground_tunnel",
        engineering_object="炮孔", process_family="钻爆参数设计", process_stage="parameter_control",
        control_points=["控制炮孔间距", "检查孔位和孔深"], quality_score=0.9, confidence=0.9,
        parameter_slots=[AtomParameterSlot(
            slot_key="blast.hole_spacing", display_name="炮孔间距", source_value=value, unit="m",
            data_type="number_with_unit", semantic_role="historical_example", reuse_policy="replace_from_evidence",
        )],
    )
    return finalize_v2_atom(atom)


if __name__ == "__main__":
    unittest.main()
