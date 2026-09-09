import asyncio
import sqlite3
from contextlib import closing
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import httpx

from coalplan.application.reference_import_service import process_reference_markdown
from coalplan.domain.documents import stable_id
from coalplan.domain.reference_library import ReferenceAtom, ReferenceReviewStatus
from coalplan.domain.generation import Project
from coalplan.domain.templates import TemplateNode
from coalplan.main import create_app
from coalplan.settings import Settings


class StudioBridgeTest(unittest.TestCase):
    def test_matcher_failure_keeps_only_valid_user_pins(self):
        with tempfile.TemporaryDirectory() as temp:
            app = create_app(Settings(storage_dir=Path(temp), llm_provider="fake", structured_llm_provider="fake"))
            pipeline = app.state.pipeline
            atom = ReferenceAtom(id="pinned", document_id="doc", project_name="Reference", project_type="road", title_path=["Process"], content="Reviewed", start_line=1, end_line=2, status=ReferenceReviewStatus.published)
            blocked = atom.model_copy(update={"id":"blocked", "publication_blockers":["missing source"]})
            pipeline.reference_library = SimpleNamespace(get_atoms=lambda _: [atom, blocked])
            with patch.object(pipeline, "get_chapter_basis_preferences", return_value={"atom_ids":["pinned","blocked"],"excluded_atom_ids":[],"prompt":""}), patch("coalplan.application.run_generation_pipeline.classify_atom_retrieval_query", side_effect=TimeoutError("model unavailable")):
                matches = pipeline._retrieve_reference_atoms(project=Project(name="Project",template_id="coal_fire"),node=TemplateNode(id="n",title="Methods",level=1),selected_sections=[],policy=None)
                self.assertEqual(["pinned"], [m.atom_id for m in matches])

    def test_library_writes_do_not_block_readers(self):
        with tempfile.TemporaryDirectory() as temp:
            create_app(Settings(storage_dir=Path(temp), llm_provider="fake", structured_llm_provider="fake"))
            with closing(sqlite3.connect(str(Path(temp)/"coalplan.db"))) as writer, closing(sqlite3.connect(str(Path(temp)/"coalplan.db"), timeout=0.1)) as reader:
                self.assertEqual("wal", reader.execute("PRAGMA journal_mode").fetchone()[0])
                writer.execute("CREATE TABLE studio_probe(value INTEGER)")
                writer.execute("INSERT INTO studio_probe VALUES (1)")
                writer.commit()
                writer.execute("BEGIN EXCLUSIVE")
                writer.execute("UPDATE studio_probe SET value=2")
                self.assertEqual(1, reader.execute("SELECT value FROM studio_probe").fetchone()[0])
                writer.rollback()

    def test_document_reader_is_scoped_to_uploaded_file(self):
        asyncio.run(self._source_flow())

    async def _source_flow(self):
        with tempfile.TemporaryDirectory() as temp:
            app = create_app(Settings(storage_dir=Path(temp), llm_provider="fake", structured_llm_provider="fake"))
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                created = await client.post("/projects", json={"name": "UI test", "template_id": "coal_fire"})
                pid = created.json()["project_id"]
                for file, text in [("a.md", "# A\n\nOnly A."), ("b.md", "# B\n\nOnly B.")]:
                    response = await client.post(f"/projects/{pid}/bid-markdown", json={"file_name": file, "content": text, "append": True})
                    self.assertEqual(200, response.status_code)
                docs = (await client.get(f"/projects/{pid}/source-documents")).json()
                doc = next(d for d in docs if d["file_name"] == "a.md")
                response = await client.get(f"/projects/{pid}/source-documents/{doc['id']}/sections")
                self.assertEqual(200, response.status_code)
                self.assertTrue(response.json())
                self.assertTrue(all("Only B" not in s["snippet"] for s in response.json()))
                self.assertEqual(404, (await client.get(f"/projects/{pid}/source-documents/not-owned/sections")).status_code)

    def test_v2_retry_retains_published_atoms(self):
        with tempfile.TemporaryDirectory() as temp:
            app = create_app(Settings(storage_dir=Path(temp), llm_provider="fake", structured_llm_provider="fake"))
            pipeline, library = app.state.pipeline, app.state.reference_library
            payload = {"file_name": "reference.md", "content": "# Process\n\nVerified source.", "schema_version": "v2"}
            def result(**kwargs):
                document = kwargs["document"]
                atom = ReferenceAtom(id="stable-atom", document_id=document.id, project_name="Reference", project_type="road", title_path=["Process"], content="Candidate", start_line=1, end_line=3, status=ReferenceReviewStatus.pending_publish)
                return SimpleNamespace(atoms=[atom], segments=[], excluded_segments=[], failed_batches=[{"error": "one failed batch"}], llm_call_count=1)
            with patch("coalplan.application.reference_atomization_v2.atomize_reference_markdown_v2", side_effect=result):
                first = process_reference_markdown(pipeline=pipeline, library=library, payload=payload)
                document_id = first["document"]["id"]
                atom = library.get_atoms(["stable-atom"])[0]
                atom.status = ReferenceReviewStatus.published
                atom.content = "Human reviewed content"
                library.replace_document_content(document_id, chapters=[], atoms=[atom])
                second = process_reference_markdown(pipeline=pipeline, library=library, payload=payload)
                saved = library.get_atoms(["stable-atom"])[0]
                self.assertEqual("Human reviewed content", saved.content)
                self.assertEqual(ReferenceReviewStatus.published, saved.status)
                self.assertEqual("partial", second["processing_status"])
                self.assertEqual(1, second["atom_count"])
