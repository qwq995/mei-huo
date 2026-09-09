from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from coalplan.application.reference_v2_corpus import prepare_v2_corpus, process_v2_corpus, route_v2_corpus


class _FailingLLM:
    def complete_json(self, prompt: str, *, schema_name: str) -> dict:
        raise RuntimeError("HTTP 402: Insufficient Balance")


class _UnexpectedLLM:
    def complete_json(self, prompt: str, *, schema_name: str) -> dict:
        raise AssertionError("excluded document must not call the LLM")


class ReferenceV2CorpusTests(unittest.TestCase):
    def test_prepare_discovers_all_markdown_and_writes_resumable_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "source"
            output = Path(temp) / "output"
            (root / "水电项目").mkdir(parents=True)
            (root / "水电项目" / "施工组织设计.md").write_text(
                "# 工程概况\n\n历史项目情况。\n\n# 开挖施工\n\n测量放样后开挖，检查合格后进入下一工序。\n",
                encoding="utf-8",
            )
            result = prepare_v2_corpus(root, output)
            manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(1, result.document_count)
            self.assertEqual("v2", manifest["schema_version"])
            self.assertEqual("水电项目", manifest["documents"][0]["project_name"])
            self.assertGreater(manifest["documents"][0]["segment_count"], 0)

    def test_failed_forced_route_keeps_previous_completed_result(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "source"
            output = Path(temp) / "output"
            root.mkdir(parents=True)
            (root / "施工组织设计.md").write_text("# 开挖施工\n\n测量放样后开挖。", encoding="utf-8")
            prepared = prepare_v2_corpus(root, output)
            manifest = json.loads(prepared.manifest_path.read_text(encoding="utf-8"))
            document_id = manifest["documents"][0]["document_id"]
            route_dir = output / "routes"
            route_dir.mkdir()
            original = {
                "status": "completed", "document_id": document_id,
                "selected_segment_count": 1, "selected_character_count": 8,
                "total_segment_count": 1, "llm_call_count": 1,
            }
            route_path = route_dir / f"{document_id}.json"
            route_path.write_text(json.dumps(original), encoding="utf-8")

            summary = route_v2_corpus(
                manifest_path=prepared.manifest_path, output_dir=output,
                llm=_FailingLLM(), force=True, concurrency=1,
            )

            self.assertEqual(1, summary["completed"])
            self.assertEqual(original, json.loads(route_path.read_text(encoding="utf-8")))
            self.assertEqual(1, len(list(route_dir.glob(f"{document_id}.attempt-*.json"))))

    def test_document_with_no_selected_technical_segments_is_excluded(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "source"
            output = Path(temp) / "output"
            root.mkdir(parents=True)
            (root / "签批附件.md").write_text("# 报审表\n\n编制：某某\n审核：某某\n", encoding="utf-8")
            prepared = prepare_v2_corpus(root, output)
            manifest = json.loads(prepared.manifest_path.read_text(encoding="utf-8"))
            document_id = manifest["documents"][0]["document_id"]
            route_dir = output / "routes"
            route_dir.mkdir()
            (route_dir / f"{document_id}.json").write_text(json.dumps({
                "status": "completed", "project_type": "签批附件",
                "selected_segment_ids": [], "routes": [],
            }), encoding="utf-8")

            summary = process_v2_corpus(
                manifest_path=prepared.manifest_path, output_dir=output, llm=_UnexpectedLLM(),
            )

            result = json.loads((output / "documents" / f"{document_id}.json").read_text(encoding="utf-8"))
            self.assertEqual("excluded_no_technical_content", result["status"])
            self.assertEqual(1, summary["excluded_no_technical_content"])
            self.assertEqual([], result["atoms"])

    def test_start_document_processes_only_requested_manifest_slice(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "source"
            output = Path(temp) / "output"
            root.mkdir(parents=True)
            (root / "01.md").write_text("# 签批页\n\n编制：甲", encoding="utf-8")
            (root / "02.md").write_text("# 签批页\n\n审核：乙", encoding="utf-8")
            prepared = prepare_v2_corpus(root, output)
            manifest = json.loads(prepared.manifest_path.read_text(encoding="utf-8"))
            route_dir = output / "routes"
            route_dir.mkdir()
            for item in manifest["documents"]:
                (route_dir / f"{item['document_id']}.json").write_text(json.dumps({
                    "status": "completed", "project_type": "签批附件",
                    "selected_segment_ids": [], "routes": [],
                }), encoding="utf-8")

            summary = process_v2_corpus(
                manifest_path=prepared.manifest_path, output_dir=output,
                llm=_UnexpectedLLM(), start_document=1, max_documents=1,
            )

            self.assertEqual(1, summary["start_document"])
            self.assertEqual(1, summary["document_count"])
            self.assertFalse((output / "documents" / f"{manifest['documents'][0]['document_id']}.json").exists())
            self.assertTrue((output / "documents" / f"{manifest['documents'][1]['document_id']}.json").exists())


if __name__ == "__main__":
    unittest.main()
