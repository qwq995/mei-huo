from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any

from coalplan.application.generate_project_profile import generate_project_profile
from coalplan.domain.documents import MarkdownSection, SourceTocItem
from coalplan.infrastructure.storage.local_artifact_repository import LocalArtifactRepository


class ProjectProfileGenerationTest(unittest.TestCase):
    def test_invalid_source_ids_are_removed_without_discarding_profile(self) -> None:
        sections = [
            MarkdownSection(
                id="sec_valid000001",
                title_path=["工程概况"],
                level=1,
                content="本项目为宁夏煤火治理工程，治理面积约7.61公顷，采用注水、钻孔灌浆、覆盖封堵等工艺。",
                source_file="bid.md",
            )
        ]
        toc_items = [
            SourceTocItem(
                section_id="sec_valid000001",
                title_path=["工程概况"],
                level=1,
                char_count=len(sections[0].content),
                snippet=sections[0].content,
            )
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            profile = generate_project_profile(
                project_id="project_test",
                toc_items=toc_items,
                sections=sections,
                llm=_ProfileWithBadSourceIdLLM(),
                artifacts=LocalArtifactRepository(Path(temp_dir)),
            )

        self.assertEqual("宁夏煤火治理工程", profile.project_name)
        self.assertEqual(["sec_valid000001"], profile.source_section_ids)
        self.assertIn("注水、钻孔灌浆、覆盖封堵", "；".join(profile.main_methods))
        self.assertTrue(any("sec_missing0001" in item for item in profile.missing_items))
        self.assertFalse(any("基础兜底画像" in item for item in profile.missing_items))

    def test_suspicious_profile_name_and_missing_fields_are_repaired_from_source(self) -> None:
        sections = [
            MarkdownSection(
                id="sec_name000001",
                title_path=["工程概况", "项目基本信息概况", "项目名称"],
                level=3,
                content="本项目为“宁夏贺兰山汝箕沟太西煤火区安全与生态治理项目一期工程北一火区治理施工”。项目位于宁夏回族自治区石嘴山市大武口区。",
                source_file="bid.md",
                start_line=1,
            ),
            MarkdownSection(
                id="sec_scope00001",
                title_path=["工程概况", "具体施工内容"],
                level=3,
                content="北一火区面积约为7.61公顷，主要施工内容包括注水降温、钻孔与灌注浆、覆盖封堵、监测评价及生态恢复。",
                source_file="bid.md",
                start_line=2,
            ),
            MarkdownSection(
                id="sec_quality001",
                title_path=["工程概况", "质量要求"],
                level=3,
                content="项目质量需符合国家、行业及地方验收标准，同时满足设计文件及其他相关规范要求。",
                source_file="bid.md",
                start_line=3,
            ),
        ]
        toc_items = [
            SourceTocItem(
                section_id=section.id,
                title_path=section.title_path,
                level=section.level,
                char_count=len(section.content),
                snippet=section.content,
            )
            for section in sections
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            profile = generate_project_profile(
                project_id="project_test",
                toc_items=toc_items,
                sections=sections,
                llm=_BadSemanticProfileLLM(),
                artifacts=LocalArtifactRepository(Path(temp_dir)),
            )

        self.assertEqual("宁夏贺兰山汝箕沟太西煤火区安全与生态治理项目一期工程北一火区治理施工", profile.project_name)
        self.assertEqual("煤火区安全与生态治理", profile.project_type)
        self.assertNotIn("生成测试", " ".join(profile.construction_scope))
        self.assertEqual("煤火区安全与生态治理", profile.project_type)
        self.assertIn("宁夏回族自治区石嘴山市大武口区", profile.location)
        self.assertTrue(any("7.61公顷" in item for item in profile.key_quantities))
        self.assertTrue({"注水降温", "钻孔", "灌注浆", "覆盖封堵"}.issubset(set(profile.main_methods)))
        self.assertTrue(any("project_name looked like a section heading" in item for item in profile.missing_items))

    def test_generic_demo_profile_name_is_repaired_from_source(self) -> None:
        sections = [
            MarkdownSection(
                id="sec_name000001",
                title_path=["工程概况", "项目名称"],
                level=2,
                content="本项目为“宁夏贺兰山汝箕沟太西煤火区安全与生态治理项目一期工程北一火区治理施工”。",
                source_file="bid.md",
                start_line=1,
            )
        ]
        toc_items = [
            SourceTocItem(
                section_id=sections[0].id,
                title_path=sections[0].title_path,
                level=sections[0].level,
                char_count=len(sections[0].content),
                snippet=sections[0].content,
            )
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            profile = generate_project_profile(
                project_id="project_test",
                toc_items=toc_items,
                sections=sections,
                llm=_GenericDemoProfileLLM(),
                artifacts=LocalArtifactRepository(Path(temp_dir)),
            )

        self.assertEqual("宁夏贺兰山汝箕沟太西煤火区安全与生态治理项目一期工程北一火区治理施工", profile.project_name)


class _ProfileWithBadSourceIdLLM:
    def complete_json(self, prompt: str, *, schema_name: str) -> dict[str, Any]:
        self.last_prompt = prompt
        self.last_schema_name = schema_name
        return {
            "project_name": "宁夏煤火治理工程",
            "project_type": "煤火治理",
            "location": "宁夏贺兰山",
            "construction_scope": ["火区治理面积约7.61公顷"],
            "key_quantities": ["治理面积约7.61公顷"],
            "main_methods": ["注水、钻孔灌浆、覆盖封堵"],
            "schedule": ["工期以合同及进度计划为准"],
            "quality_safety_environment_targets": ["满足国家、行业及地方验收标准"],
            "risk_points": ["高温火区、裂隙、复燃风险"],
            "missing_items": [],
            "source_section_ids": ["sec_valid000001", "sec_missing0001"],
        }


class _BadSemanticProfileLLM:
    def complete_json(self, prompt: str, *, schema_name: str) -> dict[str, Any]:
        return {
            "project_name": "作业技术依据",
            "project_type": None,
            "location": None,
            "construction_scope": [],
            "key_quantities": [],
            "main_methods": [],
            "schedule": [],
            "quality_safety_environment_targets": [],
            "risk_points": [],
            "missing_items": [],
            "source_section_ids": ["sec_name000001"],
        }


class _GenericDemoProfileLLM:
    def complete_json(self, prompt: str, *, schema_name: str) -> dict[str, Any]:
        return {
            "project_name": "示例项目",
            "project_type": "施工组织设计生成测试项目",
            "location": "宁夏",
            "construction_scope": ["依据投标文件生成施工组织设计正文"],
            "key_quantities": [],
            "main_methods": [],
            "schedule": [],
            "quality_safety_environment_targets": [],
            "risk_points": [],
            "missing_items": [],
            "source_section_ids": ["sec_name000001"],
        }


if __name__ == "__main__":
    unittest.main()
