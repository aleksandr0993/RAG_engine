"""Hybrid BM25 + dense retrieval over a JSONL candidate pool."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from pathlib import Path

import numpy as np

from app.config import get_settings
from app.retrieval.bm25_util import bm25_scores, min_max_norm
from app.retrieval.embed_backend import (
    corpus_fingerprint,
    cosine_similarity_query,
    embed_passages_only,
    embed_query_and_passages,
    save_cached_matrix,
    try_load_cached_matrix,
)
from app.retrieval.interface import ReviewExample
from app.retrieval.local_examples import LocalFileRetrievalBackend, gather_retrieval_pool

log = logging.getLogger(__name__)


class HybridRetrievalBackend:
    """Delegates to lexical ``LocalFileRetrievalBackend`` unless semantic mode is enabled."""

    def __init__(self, inner: LocalFileRetrievalBackend | None = None):
        self._inner = inner or LocalFileRetrievalBackend()
        self._cache_fp: str | None = None
        self._cache_matrix: np.ndarray | None = None
        self._cache_texts: tuple[str, ...] | None = None

    def _pool_matrix(self, texts: list[str]) -> np.ndarray:
        settings = get_settings()
        fp = corpus_fingerprint(texts)
        cache_dir = Path(settings.retrieval_index_dir)
        cached = try_load_cached_matrix(cache_dir, fp)
        if cached is not None and cached.shape[0] == len(texts):
            return cached.astype(np.float32)
        mat = embed_passages_only(texts)
        try:
            save_cached_matrix(cache_dir, fp, mat)
        except OSError as e:
            log.debug("Could not cache embeddings: %s", e)
        return mat

    def retrieve(
        self,
        query: str,
        criterion_code: str | None,
        limit: int = 3,
        *,
        filter_source_project: str | None = None,
        filter_section_name: str | None = None,
    ) -> Sequence[ReviewExample]:
        settings = get_settings()
        if not settings.enable_retrieval or limit <= 0:
            return []

        if not settings.enable_semantic_retrieval:
            return self._inner.retrieve(
                query,
                criterion_code,
                limit,
                filter_source_project=filter_source_project,
                filter_section_name=filter_section_name,
            )

        pool = gather_retrieval_pool(
            backend=self._inner,
            criterion_code=criterion_code,
            filter_source_project=filter_source_project,
            filter_section_name=filter_section_name,
            max_pool=800,
        )
        if not pool:
            return self._inner.retrieve(
                query,
                criterion_code,
                limit,
                filter_source_project=filter_source_project,
                filter_section_name=filter_section_name,
            )

        texts = [p.text for p in pool]
        try:
            lex = bm25_scores(query or "", texts)
            lex_n = min_max_norm(lex)
            mat = self._pool_matrix(texts)
            qv, _ = embed_query_and_passages(query or "", texts)
            sem = cosine_similarity_query(qv, mat)
            sem_n = min_max_norm(list(sem.tolist()))
        except Exception as exc:
            log.warning("Semantic leg failed (%s); falling back to BM25 only", exc)
            lex = bm25_scores(query or "", texts)
            lex_n = min_max_norm(lex)
            sem_n = [0.5] * len(texts)

        alpha = float(settings.retrieval_hybrid_alpha)
        alpha = max(0.0, min(1.0, alpha))
        combined = [alpha * lx + (1.0 - alpha) * sx for lx, sx in zip(lex_n, sem_n, strict=True)]
        order = sorted(range(len(combined)), key=lambda i: combined[i], reverse=True)
        out: list[ReviewExample] = []
        seen: set[tuple[str, str]] = set()
        for i in order:
            if len(out) >= limit:
                break
            ex = pool[i]
            k = (ex.example_id, ex.text[:200])
            if k in seen:
                continue
            seen.add(k)
            out.append(ex)
        return out
