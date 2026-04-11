"""Lightweight BM25 (Okapi) scores for hybrid retrieval."""

from __future__ import annotations

import math
import re
from collections import Counter

_TOKEN_RE = re.compile(r"[\wа-яА-ЯёЁ]+", re.UNICODE)


def _tokens(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text or "") if len(t) > 1]


def bm25_scores(query: str, corpus: list[str], *, k1: float = 1.5, b: float = 0.75) -> list[float]:
    """Return one BM25 score per document (higher is better)."""
    if not corpus:
        return []
    q = _tokens(query)
    docs = [_tokens(d) for d in corpus]
    n = len(docs)
    if not q:
        return [0.0] * n

    avgdl = sum(len(d) for d in docs) / max(n, 1)
    if avgdl <= 0:
        avgdl = 1.0

    df: dict[str, int] = {}
    for d in docs:
        for w in set(d):
            df[w] = df.get(w, 0) + 1

    scores: list[float] = []
    for d in docs:
        dl = len(d) or 1
        freqs = Counter(d)
        s = 0.0
        for w in q:
            f = freqs.get(w, 0)
            if f == 0:
                continue
            n_w = df.get(w, 0)
            idf = math.log(1.0 + (n - n_w + 0.5) / (n_w + 0.5))
            denom = f + k1 * (1.0 - b + b * (dl / avgdl))
            s += idf * ((f * (k1 + 1.0)) / denom)
        scores.append(s)
    return scores


def min_max_norm(values: list[float]) -> list[float]:
    if not values:
        return []
    lo, hi = min(values), max(values)
    if hi - lo < 1e-12:
        return [0.5 for _ in values]
    return [(v - lo) / (hi - lo) for v in values]
