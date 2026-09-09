from __future__ import annotations

from pathlib import Path
from typing import Callable

from coalplan.application.hybrid_atom_retrieval import build_atom_search_text
from coalplan.domain.reference_library import ReferenceAtom, ReferenceReviewStatus


class QdrantAtomVectorIndex:
    """Dense atom index with payload filters; imports stay optional for lightweight installs."""

    def __init__(
        self,
        *,
        embed: Callable[[list[str]], list[list[float]]],
        dimension: int,
        collection_name: str = "reference_atoms_v2",
        url: str | None = None,
        path: Path | str | None = None,
    ) -> None:
        try:
            from qdrant_client import QdrantClient
        except ImportError as exc:
            raise RuntimeError("安装 reference-vector 可选依赖后才能启用 Qdrant 原子索引") from exc
        self.embed = embed
        self.dimension = dimension
        self.collection_name = collection_name
        self.client = QdrantClient(url=url) if url else QdrantClient(path=str(path or ".coalplan-data/qdrant"))
        self._ensure_collection()

    def _ensure_collection(self) -> None:
        from qdrant_client.models import Distance, VectorParams

        if not self.client.collection_exists(self.collection_name):
            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config=VectorParams(size=self.dimension, distance=Distance.COSINE),
            )

    def reset(self) -> None:
        if self.client.collection_exists(self.collection_name):
            self.client.delete_collection(self.collection_name)
        self._ensure_collection()

    def upsert(self, atoms: list[ReferenceAtom]) -> int:
        from qdrant_client.models import PointStruct

        eligible = [
            atom for atom in atoms
            if atom.status == ReferenceReviewStatus.published
            and atom.schema_version == "v2"
            and not atom.publication_blockers
        ]
        if not eligible:
            return 0
        vectors = self.embed([build_atom_search_text(atom) for atom in eligible])
        points = [
            PointStruct(
                id=_point_id(atom.id),
                vector=vector,
                payload={
                    "atom_id": atom.id,
                    "document_id": atom.document_id,
                    "project_type": atom.project_type,
                    "chapter_module": atom.chapter_module,
                    "engineering_system": atom.engineering_system,
                    "engineering_object": atom.engineering_object,
                    "process_family": atom.process_family,
                    "process_stage": atom.process_stage,
                    "content_functions": atom.content_functions,
                    "quality_score": atom.quality_score,
                    "schema_version": atom.schema_version,
                    "status": atom.status.value,
                },
            )
            for atom, vector in zip(eligible, vectors, strict=True)
        ]
        self.client.upsert(collection_name=self.collection_name, points=points, wait=True)
        return len(points)

    def search(self, query_text: str, *, limit: int, filters: dict[str, str | list[str]]) -> list[tuple[str, float]]:
        from qdrant_client.models import FieldCondition, Filter, MatchAny, MatchValue

        conditions = []
        for key, value in filters.items():
            match = MatchAny(any=value) if isinstance(value, list) else MatchValue(value=value)
            conditions.append(FieldCondition(key=key, match=match))
        query_filter = Filter(must=conditions) if conditions else None
        points = self.client.query_points(
            collection_name=self.collection_name,
            query=self.embed([query_text])[0],
            query_filter=query_filter,
            limit=limit,
            with_payload=True,
        ).points
        return [(str(point.payload["atom_id"]), float(point.score)) for point in points]

    def delete(self, atom_ids: list[str]) -> int:
        unique_ids = list(dict.fromkeys(atom_ids))
        if not unique_ids:
            return 0
        self.client.delete(
            collection_name=self.collection_name,
            points_selector=[_point_id(atom_id) for atom_id in unique_ids],
            wait=True,
        )
        return len(unique_ids)

    def close(self) -> None:
        self.client.close()


class SentenceTransformerEmbedder:
    def __init__(self, model_name: str = "BAAI/bge-m3", device: str | None = None) -> None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError("安装 reference-vector 可选依赖后才能加载本地向量模型") from exc
        self.model = SentenceTransformer(model_name, device=device)

    @property
    def dimension(self) -> int:
        getter = getattr(self.model, "get_embedding_dimension", None)
        if getter is None:
            getter = self.model.get_sentence_embedding_dimension
        return int(getter())

    def __call__(self, texts: list[str]) -> list[list[float]]:
        vectors = self.model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
        return [vector.tolist() for vector in vectors]


def _point_id(atom_id: str) -> int:
    import hashlib

    return int.from_bytes(hashlib.sha256(atom_id.encode("utf-8")).digest()[:8], "big") & ((1 << 63) - 1)
