import unittest

from coalplan.application.reference_atom_audit import audit_atom
from coalplan.domain.reference_library import ReferenceAtom, ReferenceReviewStatus


def atom(**changes):
    value = dict(
        id="audit-1", document_id="doc-1", project_name="历史项目", project_type="水电工程",
        title_path=["总体工作方案", "�� OCR 标题"], content="洞身开挖采用光面爆破。&#x20;",
        raw_excerpt="洞身开挖采用光面爆破。&#x20;", normalized_text="", start_line=1, end_line=3,
        schema_version="v2", atom_type="process", engineering_object="隧洞", specialty="地下工程",
        process="洞挖", process_family="洞挖", chapter_module="施工方法", engineering_system="",
        action_sequence=["测量放样"], control_points=["检查孔位"], quality_score=0.9,
        status=ReferenceReviewStatus.published,
    )
    value.update(changes)
    return ReferenceAtom(**value)


class ReferenceAtomAuditTests(unittest.TestCase):
    def test_audit_blocks_requested_quality_and_missing_fields_without_inventing(self):
        audited, result = audit_atom(atom())
        self.assertIn("质量分低于 0.94", result.blockers)
        self.assertIn("缺少工程系统标签", result.blockers)
        self.assertIn("缺少验收或检查字段", result.blockers)
        self.assertIn("缺少风险字段", result.blockers)
        self.assertEqual(ReferenceReviewStatus.ai_candidate, audited.status)
        self.assertEqual([], audited.acceptance_checks)

    def test_audit_cleans_html_entity_and_detects_template_mismatch(self):
        value = atom(
            content="钻孔深度 5m。&#x20;",
            raw_excerpt="钻孔深度 5m。&#x20;",
            quality_score=0.96,
            engineering_system="地下开挖系统",
            acceptance_checks=["检查孔深"],
            risks=["塌孔"],
            parameterized_template="钻孔深度 {{project_specific.9}}。",
        )
        audited, result = audit_atom(value)
        self.assertIn("模板槽位集合与参数槽定义不一致", result.blockers)
        self.assertNotIn("&#x20;", audited.content)
        self.assertTrue(result.safe_changes)


if __name__ == "__main__":
    unittest.main()
