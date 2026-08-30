from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from coalplan.application.reference_batch_workbench import ingest_reference_decisions, prepare_reference_batches


class ReferenceBatchWorkbenchTests(unittest.TestCase):
    def test_prepare_filters_catalog_scope_and_preserves_source_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "施组.md"
            source.write_text("# 方案\n\n## 洞挖\n\n" + "测量放样后进行钻孔，检查孔位孔深，合格后装药爆破并在爆后通风排险，形成验收记录。" * 3, encoding="utf-8")
            catalog = root / "catalog.json"
            catalog.write_text(json.dumps({"documents": [
                {"document_id": "doc-1", "content_hash": "h1", "absolute_path": str(source), "relative_path": "施组.md", "file_name": "施组.md", "project_name": "示例", "project_type": "水电/地下洞室", "atom_candidate": True},
                {"document_id": "doc-2", "content_hash": "h2", "absolute_path": str(source), "relative_path": "投标.md", "file_name": "投标.md", "project_name": "投标", "project_type": "光伏", "atom_candidate": True},
            ]}, ensure_ascii=False), encoding="utf-8")
            result = prepare_reference_batches(source_root=root, catalog_path=catalog, output_dir=root / "out", batch_size=1)
            self.assertEqual(1, result.document_count)
            task = next(result.task_dir.glob("batch_*.json"))
            payload = json.loads(task.read_text(encoding="utf-8"))
            self.assertEqual("doc-1", payload["documents"][0]["document_id"])
            self.assertTrue(payload["documents"][0]["blocks"][0]["block_id"])

    def test_ingest_publishes_only_high_and_rejects_rewritten_content(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            task_dir = root / "run" / "tasks"
            decision_dir = root / "decisions"
            output_dir = root / "library"
            task_dir.mkdir(parents=True)
            decision_dir.mkdir()
            content = "测量放样后进行钻孔，检查孔位孔深，合格后装药爆破并在爆后通风排险，形成验收记录。" * 2
            task = {"run_id": "run-1", "documents": [{"document_id": "doc-1", "source_path": "示例.md", "file_name": "示例.md", "project_name": "示例", "project_type": "水电", "blocks": [{"block_id": "b1", "title_path": ["洞挖"], "start_line": 3, "end_line": 5, "content": content}]}]}
            (task_dir / "batch_0001.json").write_text(json.dumps(task, ensure_ascii=False), encoding="utf-8")
            decision = {"documents": [{"document_id": "doc-1", "atoms": [
                {"block_ids": ["b1"], "reference_value": "high", "quality_score": 0.9, "confidence": 0.9, "process": "钻爆开挖", "value_reason": "包含工序和验收闭环"},
                {"block_ids": ["b1"], "content": "模型擅自改写正文", "reference_value": "high"},
                {"block_ids": ["b1"], "reference_value": "low"},
            ]}]}
            (decision_dir / "batch_0001.json").write_text(json.dumps(decision, ensure_ascii=False), encoding="utf-8")
            summary = ingest_reference_decisions(task_dir=task_dir, decision_dir=decision_dir, output_dir=output_dir)
            self.assertEqual(1, summary["published_atom_count"])
            self.assertEqual(2, summary["rejected_count"])
            published = [json.loads(line) for line in (output_dir / "reference_atom_library.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertEqual(content, published[0]["content"])
            self.assertEqual("published", published[0]["review_status"])

    def test_missing_batch_is_reported_for_resume(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            task_dir = root / "run" / "tasks"
            task_dir.mkdir(parents=True)
            (task_dir / "batch_0001.json").write_text(json.dumps({"documents": []}), encoding="utf-8")
            summary = ingest_reference_decisions(task_dir=task_dir, decision_dir=root / "decisions", output_dir=root / "library")
            self.assertEqual(["batch_0001.json"], summary["missing_batches"])

    def test_model_dedup_group_keeps_one_atom_and_tracks_other_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            task_dir = root / "run" / "tasks"
            decision_dir = root / "decisions"
            output_dir = root / "library"
            task_dir.mkdir(parents=True)
            decision_dir.mkdir()
            block = {"block_id": "b1", "title_path": ["支护"], "start_line": 1, "end_line": 4, "content": "按照设计要求完成锚杆钻孔、清孔、注浆和安装，逐孔检查并形成验收记录。" * 3}
            docs = [{"document_id": f"doc-{n}", "source_path": f"{n}.md", "file_name": f"{n}.md", "project_name": f"项目{n}", "project_type": "水电", "blocks": [block]} for n in (1, 2)]
            (task_dir / "batch_0001.json").write_text(json.dumps({"documents": docs}, ensure_ascii=False), encoding="utf-8")
            atoms = [{"block_ids": ["b1"], "reference_value": "high", "quality_score": 0.9, "confidence": 0.9, "process": "锚杆支护", "dedup_group": "支护-锚杆"} for _ in docs]
            (decision_dir / "batch_0001.json").write_text(json.dumps({"documents": [{"document_id": "doc-1", "atoms": [atoms[0]]}, {"document_id": "doc-2", "atoms": [atoms[1]]}]}, ensure_ascii=False), encoding="utf-8")
            summary = ingest_reference_decisions(task_dir=task_dir, decision_dir=decision_dir, output_dir=output_dir)
            self.assertEqual(1, summary["published_atom_count"])
            published = json.loads((output_dir / "reference_atom_library.jsonl").read_text(encoding="utf-8"))
            self.assertEqual("2.md", published["duplicate_sources"][0]["source_document"])


if __name__ == "__main__":
    unittest.main()
