from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from coalplan.domain.reference_library import ReferenceReviewStatus
from coalplan.infrastructure.database.reference_repository import ReferenceLibraryRepository
from coalplan.infrastructure.database.session import create_session_factory
from coalplan.infrastructure.database.standard_repository import StandardConstraintRepository
from tools.seed_hydro_demo_library import seed


class HydroDemoLibraryTest(unittest.TestCase):
    def test_seed_contains_small_published_reference_and_review_libraries(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_dir = Path(temp_dir) / "hydro-demo"
            manifest = seed(storage_dir)
            session_factory = create_session_factory(f"sqlite:///{(storage_dir / 'coalplan.db').as_posix()}")
            reference_repository = ReferenceLibraryRepository(session_factory)
            standard_repository = StandardConstraintRepository(session_factory)

            self.assertEqual(5, manifest["published_reference_atom_count"])
            self.assertEqual(9, manifest["published_constraint_atom_count"])
            self.assertEqual(5, len(reference_repository.list_atoms(status=ReferenceReviewStatus.published)))
            self.assertEqual(9, len(standard_repository.list_atoms()))
            self.assertTrue((storage_dir / "reference_atoms.json").is_file())
            self.assertTrue((storage_dir / "constraint_atoms.json").is_file())


if __name__ == "__main__":
    unittest.main()
