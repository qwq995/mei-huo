from __future__ import annotations

import unittest
import tempfile
from pathlib import Path

from coalplan.application.hybrid_atom_retrieval import hybrid_prefilter_atoms
from coalplan.application.reference_atom_v2 import (
    detect_specific_tokens,
    evaluate_publication_gate,
    finalize_v2_atom,
)
from coalplan.application.reference_atomization_v2 import (
    _resolve_source_quote,
    _taxonomy_value,
    atomize_reference_markdown_v2,
    build_semantic_segments,
    load_reference_taxonomy,
)
from coalplan.application.reference_section_routing import _routing_entries, route_reference_sections
from coalplan.domain.reference_library import AtomRetrievalQuery, ReferenceAtom, ReferenceBlock, ReferenceDocument, ReferenceDocumentKind, ReferenceReviewStatus


class StubLLM:
    def __init__(self, response: dict) -> None:
        self.response = response
        self.prompts: list[str] = []

    def complete_json(self, prompt: str, *, schema_name: str) -> dict:
        self.prompts.append(prompt)
        return self.response


class FlakyLLM(StubLLM):
    def complete_json(self, prompt: str, *, schema_name: str) -> dict:
        self.prompts.append(prompt)
        if len(self.prompts) == 1:
            raise RuntimeError("temporary timeout")
        return self.response


class StubVectorIndex:
    def __init__(self, atom_ids: list[str]) -> None:
        self.atom_ids = atom_ids
        self.filters = None

    def search(self, query_text: str, *, limit: int, filters: dict) -> list[tuple[str, float]]:
        self.filters = filters
        return [(atom_id, 0.9 - index * 0.1) for index, atom_id in enumerate(self.atom_ids[:limit])]


class ReferenceAtomV2Tests(unittest.TestCase):
    def test_building_structure_process_alias_maps_to_fitout_family(self) -> None:
        self.assertEqual(
            "building_fitout",
            _taxonomy_value("building_structure", "process_families", load_reference_taxonomy()),
        )

    def test_atomization_retries_one_transient_batch_failure(self) -> None:
        markdown = "# 排水\n\n施工废水沉淀后回用，并形成检查记录。"
        document = ReferenceDocument(
            id="doc-retry", content_hash="hash-retry", source_path="retry.md", file_name="retry.md",
            project_name="历史项目", project_type="水电工程",
            document_kind=ReferenceDocumentKind.construction_organization,
        )
        llm = FlakyLLM({"atoms": [], "excluded_segments": []})

        result = atomize_reference_markdown_v2(document=document, markdown=markdown, llm=llm)

        self.assertEqual(2, result.llm_call_count)
        self.assertEqual([], result.failed_batches)

    def test_source_quote_resolution_tolerates_whitespace_but_returns_original_text(self) -> None:
        source = "平交口开挖应按照\n“短进尺、多循环、弱爆破、勤量测”的原则施工。"
        quote = "平交口开挖应按照 “短进尺、多循环、弱爆破、勤量测”的原则施工。"
        self.assertEqual(source, _resolve_source_quote(quote, source))

    def test_coarse_title_path_is_split_into_independent_route_windows(self) -> None:
        blocks = [
            ReferenceBlock(
                block_id=f"block-{index}", title_path=["施工组织设计"],
                content=("施工技术内容" * 100), start_line=index, end_line=index,
            )
            for index in range(20)
        ]
        entries = _routing_entries({("施工组织设计",): blocks})
        self.assertGreater(len(entries), 1)
        self.assertEqual(20, sum(len(item["segment_ids"]) for item in entries))
        self.assertEqual(len(entries), len({item["path_key"] for item in entries}))

    def test_parameter_slots_deduplicate_contained_detector_values(self) -> None:
        from coalplan.application.reference_atom_v2 import build_parameter_slots
        from coalplan.domain.reference_library import AtomParameterSlot

        slots = build_parameter_slots(
            "设置增压泵站，压力≥0.6MPa，主管总长约 2km。",
            [
                AtomParameterSlot(
                    slot_key="booster_pressure", display_name="增压压力", source_value="≥0.6MPa",
                    unit="MPa", data_type="number_with_unit", semantic_role="project_specific",
                    reuse_policy="keep_normative_with_version_check",
                ),
                AtomParameterSlot(
                    slot_key="pipe_length", display_name="主管长度", source_value="约 2km",
                    unit="km", data_type="number_with_unit", semantic_role="project_specific",
                    reuse_policy="replace_from_evidence",
                ),
            ],
        )

        self.assertEqual(["≥0.6MPa", "约 2km"], sorted((slot.source_value for slot in slots)))
        self.assertTrue(all(slot.reuse_policy == "replace_from_evidence" for slot in slots))
    def test_parameter_gate_catches_numbers_standards_and_project_entities(self) -> None:
        text = "某抽水蓄能电站采用C30混凝土，坍落度控制为70～90mm，并执行DL/T 5144-2015。"
        tokens = [item[0] for item in detect_specific_tokens(text)]
        self.assertIn("70～90mm", tokens)
        self.assertIn("DL/T 5144-2015", tokens)
        self.assertTrue(any("抽水蓄能电站" in item for item in tokens))
        atom = finalize_v2_atom(_atom("atom-parameter", text))
        self.assertEqual(1.0, atom.parameter_coverage)
        self.assertIn("{{project_specific.1}}", atom.parameterized_template)
        self.assertIn("{{normative_reference.1}}", atom.parameterized_template)

    def test_publication_requires_structured_tags(self) -> None:
        atom = finalize_v2_atom(_atom("atom-missing", "施工前检查设备状态，完成测量放样和工序交接，并将检查结果形成记录后方可进入下一道工序。"))
        gate = evaluate_publication_gate(atom)
        self.assertFalse(gate.allowed)
        self.assertTrue(any("文档模块" in item for item in gate.blockers))

    def test_short_but_complete_prohibition_atom_can_pass_length_gate(self) -> None:
        atom = _atom("atom-short-control", "洞内一律采用数码雷管爆破网路，严禁使用火花起爆系统。")
        atom.atom_type = "control"
        atom.chapter_module = "safety_occupational_health"
        atom.engineering_system = "underground_tunnel"
        atom.engineering_object = "洞内起爆系统"
        atom.process_family = "drilling_blasting"
        atom.control_points = ["采用数码雷管爆破网路", "严禁使用火花起爆系统"]
        atom.prohibited_scenarios = ["使用火花起爆系统"]
        atom = finalize_v2_atom(atom)
        self.assertTrue(evaluate_publication_gate(atom).allowed)

    def test_v2_atomization_preserves_source_and_builds_parameter_template(self) -> None:
        markdown = "# 隧洞工程\n\n## 钻孔爆破\n\n测量放样后钻孔，孔深控制为3.5m；装药联网检查合格后起爆，通风排烟并检查盲炮和危石，形成爆破记录。爆破后由专业人员确认警戒解除条件，对孔位、超欠挖及围岩稳定情况进行复核，不符合要求时完成处置并再次检查。\n"
        segments = build_semantic_segments(markdown)
        llm = StubLLM({"atoms": [{
            "segment_ids": [segments[0].block_id],
            "source_quotes": [segments[0].content],
            "atom_type": "process",
            "chapter_module": "process_technology",
            "engineering_system": "underground_tunnel",
            "engineering_object": "隧洞",
            "specialty": "洞挖",
            "work_item": "钻爆开挖",
            "process_family": "drilling_blasting",
            "process_method": "钻爆法",
            "process_stage": "main_operation",
            "content_functions": ["workflow", "parameter", "inspection", "record"],
            "action_sequence": ["测量放样", "钻孔", "装药联网", "起爆", "通风排烟", "爆后检查"],
            "control_points": ["装药联网检查合格后方可起爆"],
            "acceptance_checks": ["检查盲炮和危石"],
            "exceptions": [],
            "risks": ["盲炮", "危石"],
            "parameter_slots": [{
                "slot_key": "blast.hole_depth", "display_name": "炮孔深度", "source_value": "3.5m",
                "unit": "m", "data_type": "number_with_unit", "semantic_role": "design_required",
                "reuse_policy": "replace_from_evidence", "required": True
            }],
            "quality_score": 0.91,
            "confidence": 0.93,
            "value_reason": "工序和爆后检查闭环完整"
        }], "excluded_segments": []})
        document = ReferenceDocument(
            id="doc-v2", content_hash="hash-v2", source_path="sample.md", file_name="sample.md",
            project_name="历史项目", project_type="水电/隧洞", document_kind=ReferenceDocumentKind.construction_organization,
        )
        result = atomize_reference_markdown_v2(document=document, markdown=markdown, llm=llm)
        self.assertEqual(1, len(result.atoms))
        atom = result.atoms[0]
        self.assertEqual("v2", atom.schema_version)
        self.assertEqual(atom.content, atom.raw_excerpt)
        self.assertIn("{{blast.hole_depth}}", atom.parameterized_template)
        self.assertEqual(ReferenceReviewStatus.pending_publish, atom.status)
        self.assertEqual([], atom.publication_blockers)

    def test_v2_atomization_resumes_completed_batch_without_llm_call(self) -> None:
        markdown = "# 排水\n\n施工废水沉淀后回用，定期检查沉淀池并形成清理记录。"
        segment = build_semantic_segments(markdown)[0]
        response = {"atoms": [{
            "segment_ids": [segment.block_id], "source_quotes": [segment.content],
            "atom_type": "control", "chapter_module": "environmental_water_soil_civilized",
            "engineering_system": "temporary_support_system", "engineering_object": "施工排水",
            "specialty": "环境保护", "work_item": "施工废水处理",
            "process_family": "environmental_control", "process_method": "沉淀回用",
            "process_stage": "inspection_acceptance", "content_functions": ["control", "inspection", "record"],
            "applicability": [], "prohibited_scenarios": [], "action_sequence": ["沉淀", "回用"],
            "control_points": ["定期检查沉淀池"], "acceptance_checks": ["检查沉淀池"],
            "exceptions": [], "risks": [], "parameter_slots": [],
            "quality_score": 0.9, "confidence": 0.9, "value_reason": "具有处理和检查闭环",
        }], "excluded_segments": []}
        document = ReferenceDocument(
            id="doc-resume", content_hash="hash-resume", source_path="resume.md", file_name="resume.md",
            project_name="历史项目", project_type="水电工程",
            document_kind=ReferenceDocumentKind.construction_organization,
        )
        llm = StubLLM(response)
        with tempfile.TemporaryDirectory() as temp:
            first = atomize_reference_markdown_v2(
                document=document, markdown=markdown, llm=llm, checkpoint_dir=Path(temp),
            )
            second = atomize_reference_markdown_v2(
                document=document, markdown=markdown, llm=llm, checkpoint_dir=Path(temp),
            )
        self.assertEqual(1, len(llm.prompts))
        self.assertEqual(first.atoms[0].id, second.atoms[0].id)
        self.assertEqual(0, second.llm_call_count)

    def test_hybrid_retrieval_combines_tags_lexical_and_vector_rank(self) -> None:
        matching = finalize_v2_atom(_atom("matching", "测量放样后钻孔，装药联网检查后起爆，通风排烟后开展爆后安全检查并形成记录。"))
        matching.chapter_module = "process_technology"
        matching.engineering_system = "underground_tunnel"
        matching.engineering_object = "隧洞"
        matching.process_family = "drilling_blasting"
        matching.process_stage = "main_operation"
        matching.content_functions = ["workflow", "inspection"]
        matching.status = ReferenceReviewStatus.published
        matching.publication_blockers = []
        unrelated = matching.model_copy(deep=True)
        unrelated.id = "unrelated"
        unrelated.process_family = "concrete"
        vector = StubVectorIndex(["unrelated", "matching"])
        query = AtomRetrievalQuery(
            project_name="当前项目", project_type="水电/隧洞", chapter_title="钻孔爆破施工",
            chapter_module="process_technology", engineering_system="underground_tunnel",
            engineering_object="隧洞", process_family="drilling_blasting", process_stage="main_operation",
            content_functions=["workflow", "inspection"],
        )
        results = hybrid_prefilter_atoms([unrelated, matching], query, vector_index=vector)
        self.assertEqual(["matching"], [item.atom.id for item in results])
        self.assertEqual("drilling_blasting", vector.filters["process_family"])

    def test_ai_routes_project_facts_away_from_atomization(self) -> None:
        markdown = (
            "# 工程概况\n\n本工程位于某县，合同工期365天。\n\n"
            "# 隧洞开挖\n\n测量放样后钻孔，装药联网检查后起爆；通风排烟并完成盲炮、危石检查后组织出渣和支护。\n"
        )
        segments = build_semantic_segments(markdown)
        overview = next(item for item in segments if item.title_path == ["工程概况"])
        process = next(item for item in segments if item.title_path == ["隧洞开挖"])
        llm = StubLLM({
            "project_type": "水电/隧洞",
            "sections": [
                {"path_key": "工程概况", "route": "project_fact", "chapter_module": "project_overview", "reason": "历史项目事实", "confidence": 0.98},
                {"path_key": "隧洞开挖", "route": "atom_source", "chapter_module": "process_technology", "reason": "具有完整工艺闭环", "confidence": 0.95},
            ],
        })
        document = ReferenceDocument(
            id="doc-route", content_hash="hash-route", source_path="route.md", file_name="route.md",
            project_name="历史项目", project_type="待识别", document_kind=ReferenceDocumentKind.construction_organization,
        )
        result = route_reference_sections(document=document, segments=segments, llm=llm)
        self.assertEqual("水电/隧洞", result.project_type)
        self.assertNotIn(overview.block_id, [item.block_id for item in result.selected_segments])
        self.assertIn(process.block_id, [item.block_id for item in result.selected_segments])


def _atom(atom_id: str, content: str) -> ReferenceAtom:
    return ReferenceAtom(
        id=atom_id,
        document_id="doc-source",
        project_name="历史项目",
        project_type="水电/隧洞",
        title_path=["施工技术", "钻孔爆破"],
        content=content,
        start_line=10,
        end_line=20,
        atom_type="process",
        quality_score=0.9,
        confidence=0.9,
    )


if __name__ == "__main__":
    unittest.main()
