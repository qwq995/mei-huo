from __future__ import annotations

import unittest

from coalplan.domain.documents import SourceTocItem
from coalplan.domain.outline import SourceMappingMatch, SourceMappingResult, TemplateOutlineNode, TemplateOutlinePlan
from coalplan.domain.profile import ProjectProfile
from coalplan.domain.templates import TemplateNode, TemplateTree
from coalplan.infrastructure.validation.json_contract import (
    ProjectProfileValidator,
    SourceMappingValidator,
    TemplateOutlinePlanValidator,
)


class JsonContractTest(unittest.TestCase):
    def test_project_profile_rejects_unknown_source_section_id(self) -> None:
        toc_items = [_toc("sec_valid000001")]
        profile = ProjectProfile(project_name="煤火治理", source_section_ids=["sec_missing0001"])

        result = ProjectProfileValidator().validate(profile, toc_items)

        self.assertFalse(result.passed)
        self.assertIn("invalid_source_section_id", {issue.code for issue in result.issues})

    def test_template_outline_rejects_unknown_node_and_missing_modules(self) -> None:
        template = TemplateTree(
            id="coal_fire",
            name="煤火模板",
            nodes=[TemplateNode(id="tpl_valid", title="火区位置", level=2)],
        )
        toc_items = [_toc("sec_valid000001")]
        outline = TemplateOutlinePlan(
            template_id="coal_fire",
            nodes=[
                TemplateOutlineNode(node_id="tpl_missing", title="虚构章节", level=2, source_hints=["sec_missing0001"]),
                TemplateOutlineNode(node_id="tpl_valid", title="火区位置", level=2, main_sources=[], auto_fill=[], manual_fill=[]),
            ],
        )

        result = TemplateOutlinePlanValidator().validate(outline, template, toc_items)

        self.assertFalse(result.passed)
        codes = {issue.code for issue in result.issues}
        self.assertIn("invalid_template_node_id", codes)
        self.assertIn("invalid_source_hint", codes)
        self.assertIn("missing_outline_modules", codes)

    def test_source_mapping_rejects_unknown_section_id(self) -> None:
        toc_items = [_toc("sec_valid000001")]
        mapping = SourceMappingResult(
            node_id="tpl_valid",
            matches=[SourceMappingMatch(section_id="sec_missing0001", confidence=0.8)],
        )

        result = SourceMappingValidator().validate(mapping, toc_items)

        self.assertFalse(result.passed)
        self.assertIn("invalid_mapping_section_id", {issue.code for issue in result.issues})


def _toc(section_id: str) -> SourceTocItem:
    return SourceTocItem(section_id=section_id, title_path=["工程概况"], level=1)


if __name__ == "__main__":
    unittest.main()
