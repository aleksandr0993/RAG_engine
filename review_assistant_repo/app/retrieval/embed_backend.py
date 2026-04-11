"""
Embedding helpers for semantic retrieval (OpenAI API or local sentence-transformers).

Caches dense vectors under ``retrieval_index_dir`` keyed by corpus fingerprint (optional).
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

import numpy as np

from app.config import get_settings

log = logging.getLogger(__name__)


def _l2_normalize_rows(mat: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    norms = np.maximum(norms, 1e-12)
    return mat / norms


def embed_texts_openai(texts: list[str]) -> np.ndarray:
    """Batch embeddings via OpenAI-compatible ``/v1/embeddings``."""
    import httpx

    settings = get_settings()
    key = settings.llm_api_key
    if not key or not str(key).strip():
        raise RuntimeError("OPENAI / LLM API key required for embedding_model=openai")
    base = (settings.llm_base_url or "https://api.openai.com/v1").rstrip("/")
    url = f"{base}/embeddings"
    model = settings.openai_embedding_model
    out_vecs: list[list[float]] = []
    batch = 64
    with httpx.Client(timeout=120.0) as client:
        for i in range(0, len(texts), batch):
            chunk = texts[i : i + batch]
            resp = client.post(
                url,
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json={"model": model, "input": chunk},
            )
            resp.raise_for_status()
            data = resp.json()
            rows = sorted(data.get("data") or [], key=lambda x: int(x.get("index", 0)))
            for row in rows:
                out_vecs.append(row["embedding"])
    arr = np.asarray(out_vecs, dtype=np.float32)
    return _l2_normalize_rows(arr)


def _local_model():
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as e:
        raise ImportError(
            "Local embeddings need sentence-transformers. Install: pip install -e .[analysis]"
        ) from e

    return SentenceTransformer("intfloat/multilingual-e5-small")


def embed_query_and_passages_openai(query: str, passages: list[str]) -> tuple[np.ndarray, np.ndarray]:
    all_texts = [query or ""] + list(passages)
    mat = embed_texts_openai(all_texts)
    return mat[0], mat[1:]


def embed_query_and_passages_local(query: str, passages: list[str]) -> tuple[np.ndarray, np.ndarray]:
    model = _local_model()
    qv = model.encode(
        f"query: {query or ''}",
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    pv = model.encode(
        [f"passage: {t}" for t in passages],
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    return np.asarray(qv, dtype=np.float32), np.asarray(pv, dtype=np.float32)


def embed_query_and_passages(query: str, passages: list[str]) -> tuple[np.ndarray, np.ndarray]:
    settings = get_settings()
    mode = (settings.embedding_model or "local").strip().lower()
    if mode == "openai":
        return embed_query_and_passages_openai(query, passages)
    return embed_query_and_passages_local(query, passages)


def embed_passages_only(texts: list[str]) -> np.ndarray:
    """Dense vectors for corpus passages (``passage:`` prefix for e5)."""
    settings = get_settings()
    mode = (settings.embedding_model or "local").strip().lower()
    if mode == "openai":
        return embed_texts_openai(texts)
    model = _local_model()
    emb = model.encode(
        [f"passage: {t}" for t in texts],
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    return np.asarray(emb, dtype=np.float32)


def embed_texts(texts: list[str]) -> np.ndarray:
    """Embed a homogeneous batch (OpenAI or local with ``query:`` prefix for e5)."""
    settings = get_settings()
    mode = (settings.embedding_model or "local").strip().lower()
    if mode == "openai":
        return embed_texts_openai(texts)
    model = _local_model()
    emb = model.encode(
        [f"query: {t}" for t in texts],
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    return np.asarray(emb, dtype=np.float32)


def cosine_similarity_query(q: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    """q: (d,), matrix: (n,d), L2-normalized."""
    return np.dot(matrix, q.astype(np.float32))


def try_load_cached_matrix(cache_dir: Path, fp: str) -> np.ndarray | None:
    path = cache_dir / f"emb_{fp}.npy"
    if not path.is_file():
        return None
    try:
        return np.load(path)
    except OSError:
        return None


def save_cached_matrix(cache_dir: Path, fp: str, matrix: np.ndarray) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"emb_{fp}.npy"
    np.save(path, matrix)


def corpus_fingerprint(texts: list[str]) -> str:
    h = hashlib.sha256()
    for t in texts:
        h.update(t.encode("utf-8", errors="ignore"))
        h.update(b"\n")
    return h.hexdigest()[:24]
