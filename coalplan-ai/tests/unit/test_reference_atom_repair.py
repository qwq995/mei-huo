import unittest

from coalplan.application.reference_atom_repair import repair_atom
from coalplan.domain.reference_library import ReferenceAtom


class ReferenceAtomRepairTests(unittest.TestCase):
    def test_repairs_tags_and_source_grounded_checks(self):
        atom = ReferenceAtom(
            id="repair-1", document_id="doc-1", project_name="样本", project_type="水电工程",
            title_path=["灌浆施工"], content="灌浆压力应按设计要求控制，施工后检查记录完整。",
            raw_excerpt="灌浆压力应按设计要求控制，施工后检查记录完整。", start_line=1, end_line=1,
            schema_version="v2", atom_type="process", process="灌浆", process_family="灌浆",
            chapter_module="施工方法", quality_score=0.95,
        )
        fixed, outcome = repair_atom(atom)
        self.assertEqual("灌浆系统", fixed.engineering_system)
        self.assertTrue(any("验收" in item for item in outcome.repaired))
        self.assertTrue(fixed.parameterized_template)

    def test_does_not_invent_repair_for_corrupted_excerpt(self):
        atom = ReferenceAtom(
            id="repair-2", document_id="doc-1", project_name="样本", project_type="水电工程",
            title_path=["��标题"], content="��乱码", raw_excerpt="��乱码", start_line=1, end_line=1,
            schema_version="v2", atom_type="process", quality_score=0.95,
        )
        _, outcome = repair_atom(atom)
        self.assertFalse(outcome.publishable)
        self.assertTrue(any("OCR" in item or "编码" in item for item in outcome.unresolved))


if __name__ == "__main__":
    unittest.main()
