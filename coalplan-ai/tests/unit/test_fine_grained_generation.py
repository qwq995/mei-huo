from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from coalplan.application.chapter_writing_units import (
    ChapterWritingUnitContext,
    plan_chapter_writing_units,
    select_evidence_for_writing_unit,
    select_sections_for_writing_unit,
)
from coalplan.application.generate_chapter import (
    audit_unsupported_management_claims,
    build_writing_unit_prompt,
    generate_chapter,
)
from coalplan.application.generation_context import (
    initialize_generation_context,
    render_generation_context_for_prompt,
    update_generation_context,
)
from coalplan.domain.documents import MarkdownSection
from coalplan.domain.generation import ChapterTask, SourceMatch
from coalplan.domain.generation_context import WritingUnitTrace
from coalplan.domain.generation_control import ChapterGenerationPolicy
from coalplan.domain.outline import SourceEvidenceSpan, SourceMappingResult, TemplateOutlinePlan
from coalplan.domain.profile import ProjectProfile
from coalplan.domain.reference_library import (
    AtomRetrievalResult,
    ReferenceAtom,
    ReferenceReviewStatus,
)
from coalplan.domain.templates import TemplateNode
from coalplan.infrastructure.llm.fake_llm import FakeLLMClient
from coalplan.infrastructure.storage.local_artifact_repository import LocalArtifactRepository


class FineGrainedGenerationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.node = TemplateNode(
            id="node_concrete",
            title="尾水洞衬砌混凝土施工",
            level=3,
            source_rules=["依据投标文件衬砌混凝土章节"],
            auto_fill=["组织模板钢筋、入仓振捣、养护和质量检查"],
            manual_fill=["最终配合比和设备配置需人工确认"],
            target_word_count=1800,
            matched_skill_keys=["construction-craft-chapter"],
            chapter_summary={
                "overview": "组织尾水洞衬砌混凝土施工。",
                "writing_unit_hints": ["入仓布料", "平仓振捣", "质量检查"],
            },
        )

        self.policy = ChapterGenerationPolicy(
            node_id=self.node.id,
            title=self.node.title,
            detail_level="subsection_required",
            target_word_count=1800,
            split_required=True,
            source_subtopics=["施工准备", "入仓布料", "平仓振捣", "质量检查", "安全环保控制"],
            required_subtopics=["异常处置"],
            writing_pattern_key="craft",
        )
        self.section = MarkdownSection(
            id="sec_concrete",
            title_path=["投标文件", "衬砌混凝土", "入仓振捣"],
            level=3,
            content="混凝土采用泵送入仓，两侧同步下料。振捣应快插慢拔，浇筑完成后进行质量检查。",
            source_file="bid.md",
        )
        self.evidence = SourceEvidenceSpan(
            evidence_id="ev_concrete",
            section_id=self.section.id,
            title_path=self.section.title_path,
            quote=self.section.content,
            summary="泵送入仓、同步下料并进行振捣和质量检查。",
            matched_terms=["入仓", "振捣", "质量检查"],
            confidence=0.9,
        )

    def test_management_claim_audit_uses_bid_text_instead_of_generated_text(self) -> None:
        markdown = (
            "爆破试验计划报监理人审批。"
            "爆破器材存放于专用库房并接受当地公安机关监管，所有人员持证上岗。"
        )

        issues = audit_unsupported_management_claims(
            generated_markdown=markdown,
            trusted_project_text="承包人应提交爆破试验计划报监理人审批。",
        )

        self.assertTrue(any("专用库房" in item for item in issues))
        self.assertTrue(any("公安机关" in item for item in issues))
        self.assertTrue(any("持证上岗" in item for item in issues))
        self.assertFalse(any(item == "爆破试验计划报监理人审批。" for item in issues))

    def test_dense_chapter_is_split_into_bounded_semantic_units(self) -> None:
        units = plan_chapter_writing_units(node=self.node, policy=self.policy)

        self.assertGreaterEqual(len(units), 2)
        self.assertLessEqual(len(units), 4)
        self.assertTrue(all(350 <= item.target_word_count <= 850 for item in units))
        self.assertTrue(any("入仓布料" in item.writing_topics for item in units))
        self.assertTrue(any("质量检查" in item.writing_topics for item in units))

    def test_blasting_unit_does_not_select_grouting_only_evidence(self) -> None:
        blast_node = self.node.model_copy(update={"id": "blast", "title": "钻孔与装药爆破"})
        policy = self.policy.model_copy(
            update={
                "node_id": "blast",
                "title": "钻孔与装药爆破",
                "source_subtopics": ["炮孔检查", "装药联网", "起爆", "爆后检查"],
            }
        )
        spec = plan_chapter_writing_units(node=blast_node, policy=policy)[0]
        blast = self.evidence.model_copy(
            update={
                "evidence_id": "ev_blast",
                "summary": "炮孔检查合格后装药联网并实施起爆。",
                "quote": "钻孔完成后进行装药、联网和爆破。",
            }
        )
        grouting = self.evidence.model_copy(
            update={
                "evidence_id": "ev_grouting",
                "summary": "灌浆试验确定注浆压力。",
                "quote": "帷幕灌浆采用分序加密施工。",
            }
        )

        selected = select_evidence_for_writing_unit([grouting, blast], spec)

        self.assertEqual(["ev_blast"], [item.evidence_id for item in selected])

    def test_unit_prompt_has_bid_atom_and_writing_skill_as_separate_roles(self) -> None:
        spec = plan_chapter_writing_units(node=self.node, policy=self.policy)[1]
        atom = ReferenceAtom(
            id="atom_demo",
            document_id="doc_demo",
            project_name="异项目",
            project_type="水电/隧洞",
            title_path=["混凝土施工", "入仓振捣"],
            content="参考项目采用分层入仓、连续振捣和检查记录闭环。",
            start_line=10,
            end_line=12,
            specialty="水工混凝土",
            work_item="衬砌混凝土",
            process="混凝土浇筑",
            process_stage="入仓振捣",
            status=ReferenceReviewStatus.published,
        )
        result = AtomRetrievalResult(
            atom_id=atom.id,
            score=0.82,
            match_reason="工艺阶段相同",
            prompt_use="借鉴入仓、振捣、检查的组织顺序",
            atom=atom,
        )
        context = ChapterWritingUnitContext(
            spec=spec,
            selected_source_sections=select_sections_for_writing_unit([self.section], spec),
            evidence_spans=select_evidence_for_writing_unit([self.evidence], spec),
            reference_atom_results=[result],
        )
        task = ChapterTask(node_id=self.node.id, title=self.node.title)

        prompt = build_writing_unit_prompt(
            node=self.node,
            task=task,
            context=context,
            project_profile=ProjectProfile(project_name="当前项目", project_type="水电/尾水洞"),
            user_context="",
            global_context='{"terminology":["尾水洞"]}',
            completed_unit_context=[],
            required_fact_hints=[],
            generation_policy=self.policy,
        )

        self.assertIn("三源输入一：当前项目投标证据", prompt)
        self.assertIn("ev_concrete", prompt)
        self.assertIn("三源输入二：高相关优秀原子", prompt)
        self.assertIn("atom_demo", prompt)
        self.assertIn("三源输入三：写作组织技巧", prompt)
        self.assertIn("construction-craft-chapter", prompt)
        self.assertIn("不得迁移", prompt)

    def test_unit_generation_assembles_one_valid_chapter_and_records_trace(self) -> None:
        specs = plan_chapter_writing_units(node=self.node, policy=self.policy)
        contexts = [
            ChapterWritingUnitContext(
                spec=spec,
                selected_source_sections=[self.section],
                evidence_spans=[self.evidence],
            )
            for spec in specs
        ]
        task = ChapterTask(
            node_id=self.node.id,
            title=self.node.title,
            target_word_count=2200,
            source_matches=[
                SourceMatch(
                    section_id=self.section.id,
                    title_path=self.section.title_path,
                    snippet=self.evidence.summary,
                    score=0.9,
                )
            ],
            source_mapping=SourceMappingResult(node_id=self.node.id, evidence=[self.evidence]),
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            draft = generate_chapter(
                project_id="project_demo",
                node=self.node,
                task=task,
                llm=FakeLLMClient(),
                artifacts=LocalArtifactRepository(Path(temp_dir)),
                project_profile=ProjectProfile(project_name="当前项目"),
                selected_source_sections=[self.section],
                generation_policy=self.policy,
                writing_unit_contexts=contexts,
                global_context='{"project_overview":"当前项目"}',
            )

        self.assertIn(f"# {self.node.title}", draft.markdown)
        self.assertEqual(1, draft.markdown.count("## 主要来源摘要"))
        self.assertEqual(1, draft.markdown.count("## 生成正文"))
        self.assertEqual(len(specs), len(draft.generation_metadata["writing_units"]))
        self.assertEqual("writing_unit", draft.generation_metadata["generation_granularity"])
        self.assertTrue(
            all(
                item["prompt_source_roles"] == ["bid_evidence", "reference_atoms", "writing_skills"]
                for item in draft.generation_metadata["writing_units"]
            )
        )

    def test_generation_context_rolls_forward_and_is_renderable(self) -> None:
        state = initialize_generation_context(
            profile=ProjectProfile(
                project_name="当前项目",
                project_type="水电/尾水洞",
                construction_scope=["尾水洞衬砌施工"],
            ),
            outline=TemplateOutlinePlan(template_id="demo"),
        )
        task = ChapterTask(node_id=self.node.id, title=self.node.title)
        with tempfile.TemporaryDirectory() as temp_dir:
            draft = generate_chapter(
                project_id="project_demo",
                node=self.node,
                task=task,
                llm=FakeLLMClient(),
                artifacts=LocalArtifactRepository(Path(temp_dir)),
            )
        trace = WritingUnitTrace(
            unit_id="unit_demo",
            title="入仓振捣",
            target_word_count=600,
            source_section_ids=["sec_concrete"],
            evidence_ids=["ev_concrete"],
        )

        state, summary = update_generation_context(
            state=state,
            node=self.node,
            draft=draft,
            writing_units=[trace],
            reference_atom_ids=[],
            llm=FakeLLMClient(),
            trusted_project_text="尾水洞衬砌混凝土采用分段浇筑。",
        )

        self.assertEqual([self.node.id], state.generated_node_order)
        self.assertEqual(self.node.id, summary.node_id)
        rendered = render_generation_context_for_prompt(state, current_node_id="next_node")
        self.assertIn("当前项目", rendered)
        self.assertIn(self.node.title, rendered)


if __name__ == "__main__":
    unittest.main()
