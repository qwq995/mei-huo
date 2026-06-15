from __future__ import annotations

from .keyword_retriever import KeywordSourceRetriever


class HybridSourceRetriever(KeywordSourceRetriever):
    """Placeholder for future vector + keyword retrieval.

    The first prototype intentionally uses keyword retrieval only, while exposing
    this class so the application layer does not change when embeddings arrive.
    """

