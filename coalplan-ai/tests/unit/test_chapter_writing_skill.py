import unittest

from coalplan.application.chapter_writing_skill import (
    build_chapter_writing_skill_prompt,
    generate_chapter_writing_skill,
    render_chapter_writing_skill,
)
from coalplan.domain.templates import TemplateNode


class FakeStructuredLLM:
    def __init__(self, response):
        self.response = response
        self.prompts = []

    def complete_json(self, prompt: str, *, schema_name: str):
        self.prompts.append((prompt, schema_name))
        return self.response


class ChapterWritingSkillTest(unittest.TestCase):
    def test_skill_uses_llm_result_and_renders_executable_sections(self) -> None:
        node = TemplateNode(id="grout", title="灌浆施工", level=3, source_rules=["灌浆来源"])
        llm = FakeStructuredLLM(
            {
                "skill_id": "chapter_skill_grout",
                "category": "工艺类章节",
                "mission": "按来源组织灌浆工艺和检查闭环。",
                "organization_logic": ["先条件后工艺，再检查验收"],
                "coverage_plan": [
                    {
                        "topic": "灌浆流程",
                        "required_points": ["施工准备", "钻孔", "灌浆", "封孔"],
                        "evidence_expectation": "参数必须来自投标证据。",
                        "acceptance_checks": ["工序是否完整"],
                    }
                ],
                "fact_boundary_rules": ["无依据参数转人工补充"],
                "prompt_instructions": ["只输出当前写作单元正文"],
            }
        )

        skill = generate_chapter_writing_skill(
            node=node,
            project_profile={"project_type": "水电"},
            global_context="全局重点：洞挖与灌浆接口。",
            policy=None,
            selected_sections=[],
            llm=llm,
        )

        self.assertEqual("chapter_skill_grout", skill.skill_id)
        self.assertEqual("llm", skill.generated_by)
        rendered = render_chapter_writing_skill(skill)
        self.assertIn("先条件后工艺", rendered)
        self.assertIn("参数必须来自投标证据", rendered)
        self.assertEqual("ChapterWritingSkill", llm.prompts[0][1])
        self.assertIn("全局重点", llm.prompts[0][0])

    def test_prompt_keeps_skill_as_instruction_not_fact_source(self) -> None:
        node = TemplateNode(id="overview", title="工程概况", level=2)
        prompt = build_chapter_writing_skill_prompt(
            node=node,
            project_profile=None,
            global_context="",
            policy=None,
            selected_sections=[],
        )
        self.assertIn("不是项目事实摘要", prompt)
        self.assertIn("不得在 Skill 中创造工程量", prompt)


if __name__ == "__main__":
    unittest.main()
