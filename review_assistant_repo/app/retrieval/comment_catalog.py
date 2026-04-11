"""
Build a non-authoritative reference catalog of typical reviewer comments from many .ipynb files.

Clusters by notebook section + Bootstrap alert color (severity proxy) and optional TF-IDF+KMeans.
Not grading truth — reviewer tendencies only.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.retrieval.notebook_training import extract_rows_from_ipynb

_ALERT_RE = re.compile(
    r'class\s*=\s*["\'][^"\']*alert-(danger|warning|success)',
    re.IGNORECASE,
)
_TOKEN_RE = re.compile(r"[\wа-яА-ЯёЁ]+", re.UNICODE)

NON_AUTHORITY_NOTE_EN = (
    "Non-authoritative: reflects reviewer phrasing tendencies across notebooks; "
    "not a rubric, not ground truth, not an official criterion map."
)
NON_AUTHORITY_NOTE_RU = (
    "Не является рубрикой и не задаёт эталонных оценок: только типичные формулировки ревьюеров."
)


def detect_alert_color(source: str) -> str:
    """
    Parse Bootstrap alert class from reviewer HTML cell source.
    Returns danger | warning | success | unknown.
    """
    if not source:
        return "unknown"
    m = _ALERT_RE.search(source)
    if not m:
        return "unknown"
    return m.group(1).lower()


def _normalize_tokens(text: str) -> set[str]:
    return {t.lower() for t in _TOKEN_RE.findall(text or "") if len(t) > 1}


def jaccard_similarity(a: str, b: str) -> float:
    sa, sb = _normalize_tokens(a), _normalize_tokens(b)
    if not sa and not sb:
        return 1.0
    if not sa or not sb:
        return 0.0
    inter = len(sa & sb)
    union = len(sa | sb)
    return inter / union if union else 0.0


def extract_catalog_rows(
    ipynb_paths: Iterable[Path | str],
    *,
    source_project: str,
    include_student_samples: bool = False,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """
    Load reviewer/middle rows from each .ipynb and attach ``alert_color``.
    Returns (catalog_rows, student_samples) where student_samples is empty unless requested.
    """
    rows: list[dict[str, Any]] = []
    student_samples: list[dict[str, Any]] = []
    for raw in ipynb_paths:
        path = Path(raw)
        if not path.is_file():
            continue
        runtime, finetune = extract_rows_from_ipynb(path, source_project=source_project)
        for r in runtime:
            d = dict(r)
            d["alert_color"] = detect_alert_color(str(d.get("text", "")))
            rows.append(d)
        if include_student_samples:
            for r in finetune:
                if r.get("author_role") != "student":
                    continue
                student_samples.append(
                    {
                        "text": (r.get("review_text") or r.get("text") or "")[:2000],
                        "source_notebook": r.get("source_notebook", ""),
                        "section_name": r.get("section_name", ""),
                        "source_project": r.get("source_project", ""),
                    }
                )
    return rows, student_samples


def _group_key(row: dict[str, Any]) -> tuple[str, str]:
    sec = str(row.get("section_name") or "").strip() or "_none"
    col = str(row.get("alert_color") or "unknown").strip() or "unknown"
    return sec, col


def _pick_representative(variants: list[str]) -> str:
    if not variants:
        return ""
    cnt = Counter(variants)
    best_freq = max(cnt.values())
    candidates = [v for v, c in cnt.items() if c == best_freq]
    return max(candidates, key=len)


def cluster_heuristic(
    rows: list[dict[str, Any]], *, sim_threshold: float = 0.55
) -> list[dict[str, Any]]:
    """
    Within each (section, alert_color) bucket, merge rows with pairwise Jaccard >= threshold (greedy).

    Returns ``[{"members": [...], "representative": None}, ...]`` (representative filled later).
    """
    buckets: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        buckets.setdefault(_group_key(row), []).append(row)

    grouped: list[dict[str, Any]] = []
    for _key, bucket in buckets.items():
        sorted_rows = sorted(bucket, key=lambda r: len(str(r.get("text", ""))), reverse=True)
        clusters: list[list[dict[str, Any]]] = []
        for row in sorted_rows:
            text = str(row.get("text", ""))
            placed = False
            for cl in clusters:
                if any(jaccard_similarity(text, str(x.get("text", ""))) >= sim_threshold for x in cl):
                    cl.append(row)
                    placed = True
                    break
            if not placed:
                clusters.append([row])
        for cl in clusters:
            grouped.append({"members": cl, "representative": None})
    return grouped


def _auto_k_sqrt(n: int) -> int:
    if n <= 1:
        return 1
    k = max(1, int(round(math.sqrt(n))))
    return min(k, n)


def _k_fixed_or_sqrt(n: int, n_clusters: int | None) -> int:
    if n <= 1:
        return 1
    if n_clusters is not None and n_clusters > 0:
        return min(n_clusters, n)
    return _auto_k_sqrt(n)


def _best_k_silhouette(X: Any, n_samples: int) -> int:
    """Pick k in [2, min(12, n//2)] maximizing silhouette (cosine on TF-IDF)."""
    from sklearn.cluster import KMeans
    from sklearn.metrics import silhouette_score

    k_hi = min(12, max(2, n_samples // 2))
    k_lo = 2
    if k_hi < k_lo or n_samples < k_lo + 1:
        return 1
    best_k, best_score = k_lo, -1.0
    for k in range(k_lo, k_hi + 1):
        if k >= n_samples:
            break
        km = KMeans(n_clusters=k, random_state=42, n_init=10, max_iter=50)
        labels = km.fit_predict(X)
        if len(set(labels)) < 2:
            continue
        try:
            s = silhouette_score(X, labels, metric="cosine")
        except ValueError:
            continue
        if s > best_score:
            best_score = s
            best_k = k
    return best_k if best_score >= 0 else _auto_k_sqrt(n_samples)


def _representative_nearest_centroid(
    members: list[dict[str, Any]],
    texts: list[str],
    X: Any,
    labels: list[int],
    cluster_label: int,
    centroids: Any,
) -> str:
    """TF-IDF row closest to KMeans centroid (cosine distance)."""
    import numpy as np
    from sklearn.metrics.pairwise import cosine_distances

    idxs = [i for i, lab in enumerate(labels) if lab == cluster_label]
    if not idxs:
        return ""
    sub = X[idxs]
    cent = centroids[cluster_label]
    dists = cosine_distances(sub, cent.reshape(1, -1)).ravel()
    best_local = int(np.argmin(dists))
    global_i = idxs[best_local]
    return str(texts[global_i]).strip()


def cluster_tfidf_kmeans(
    rows: list[dict[str, Any]],
    *,
    n_clusters: int | None = None,
    auto_k_method: str = "sqrt",
) -> list[dict[str, Any]]:
    """
    Within each (section, alert_color) bucket, cluster texts with TF-IDF + KMeans.

    Returns ``[{"members": [...], "representative": str | None}, ...]`` where ``representative``
    is the text closest to the cluster centroid (cosine); ``None`` falls back to frequency heuristic.

    Requires optional dependency: pip install -e .[analysis]
    """
    try:
        from sklearn.cluster import KMeans
        from sklearn.feature_extraction.text import TfidfVectorizer
    except ImportError as e:  # pragma: no cover - covered by optional test path
        raise ImportError(
            "tfidf_kmeans requires scikit-learn. Install: pip install -e .[analysis]"
        ) from e

    method = (auto_k_method or "sqrt").strip().lower()
    if method not in ("sqrt", "silhouette", "fixed"):
        raise ValueError("auto_k_method must be sqrt, silhouette, or fixed")

    buckets: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        buckets.setdefault(_group_key(row), []).append(row)

    grouped: list[dict[str, Any]] = []
    for _key, bucket in buckets.items():
        texts = [str(r.get("text", "")) for r in bucket]
        n = len(texts)
        if n == 0:
            continue
        if n == 1:
            grouped.append({"members": bucket, "representative": None})
            continue

        vec = TfidfVectorizer(max_features=5000, ngram_range=(1, 2), min_df=1)
        X = vec.fit_transform(texts)

        if method == "silhouette":
            k = _best_k_silhouette(X, n)
        elif method == "fixed":
            k = _k_fixed_or_sqrt(n, n_clusters)
        else:
            k = _auto_k_sqrt(n)

        if k <= 1 or k >= n:
            grouped.append({"members": bucket, "representative": None})
            continue

        km = KMeans(n_clusters=k, random_state=42, n_init=10, max_iter=50)
        labels_arr = km.fit_predict(X)
        labels = [int(x) for x in labels_arr]
        by_label: dict[int, list[dict[str, Any]]] = {}
        for row, lab in zip(bucket, labels, strict=True):
            by_label.setdefault(int(lab), []).append(row)

        centroids = km.cluster_centers_
        for lab in sorted(by_label.keys()):
            members = by_label[lab]
            rep = _representative_nearest_centroid(members, texts, X, labels, lab, centroids)
            grouped.append({"members": members, "representative": rep or None})
    return grouped


def _cluster_to_entry(
    cluster_id: str,
    members: list[dict[str, Any]],
    *,
    representative_override: str | None = None,
) -> dict[str, Any]:
    variants = [str(m.get("text", "")).strip() for m in members if str(m.get("text", "")).strip()]
    nbs = sorted({str(m.get("source_notebook", "")) for m in members if m.get("source_notebook")})
    crits = {str(m.get("criterion_code", "")).strip() for m in members if str(m.get("criterion_code", "")).strip()}
    roles = sorted({str(m.get("author_role", "")) for m in members if m.get("author_role")})
    sec = str(members[0].get("section_name") or "").strip() or "_none"
    col = str(members[0].get("alert_color") or "unknown")
    rep = (representative_override or "").strip() if representative_override else ""
    if not rep:
        rep = _pick_representative(variants)
    return {
        "cluster_id": cluster_id,
        "section": sec if sec != "_none" else "",
        "alert_color": col,
        "criterion_code": next(iter(crits)) if len(crits) == 1 else "",
        "criterion_codes_distinct": sorted(crits),
        "author_roles": roles,
        "representative_text": rep,
        "frequency": len(members),
        "source_notebooks": nbs,
        "variants": variants[:20] if len(variants) > 20 else variants,
        "variant_count": len(variants),
    }


def build_catalog(
    *,
    ipynb_paths: list[Path] | None = None,
    rows: list[dict[str, Any]] | None = None,
    source_project: str = "catalog",
    method: str = "heuristic",
    sim_threshold: float = 0.55,
    n_clusters: int | None = None,
    auto_k_method: str = "sqrt",
    min_cluster_frequency: float = 0.0,
    min_cluster_abs: int | None = None,
    include_student: bool = False,
) -> dict[str, Any]:
    """
    Build catalog dict. Supply either ``ipynb_paths`` or pre-extracted ``rows`` (with alert_color set if from custom source).

    ``min_cluster_frequency`` (e.g. 0.05): clusters smaller than this fraction of all reviewer comments go to
    ``rare_patterns`` with ``is_outlier: true``. ``min_cluster_abs`` adds an absolute minimum count when set.
    """
    student_samples: list[dict[str, Any]] = []
    if rows is None:
        if not ipynb_paths:
            rows = []
        else:
            rows, student_samples = extract_catalog_rows(
                ipynb_paths,
                source_project=source_project,
                include_student_samples=include_student,
            )
    elif include_student:
        # Caller passed rows only; cannot infer students without re-parse — document in docstring
        pass

    review_rows = [r for r in rows if r.get("author_role") != "student"]

    if method == "heuristic":
        grouped = cluster_heuristic(review_rows, sim_threshold=sim_threshold)
    elif method == "tfidf_kmeans":
        grouped = cluster_tfidf_kmeans(
            review_rows, n_clusters=n_clusters, auto_k_method=auto_k_method
        )
    else:
        raise ValueError(f"Unknown method: {method!r}, expected heuristic or tfidf_kmeans")

    catalog_list: list[dict[str, Any]] = []
    for i, g in enumerate(grouped):
        members = g.get("members") or []
        if not members:
            continue
        sec, col = _group_key(members[0])
        cid = f"{sec}__{col}__{i}"
        ro = g.get("representative")
        rep_override = str(ro).strip() if ro else None
        catalog_list.append(
            _cluster_to_entry(cid, members, representative_override=rep_override)
        )

    catalog_list.sort(key=lambda x: (x["section"], x["alert_color"], -x["frequency"]))

    unique_notebooks = len({str(r.get("source_notebook", "")) for r in review_rows if r.get("source_notebook")})
    total_comments = len(review_rows) or 1

    main_entries: list[dict[str, Any]] = []
    rare_entries: list[dict[str, Any]] = []
    abs_thr = int(min_cluster_abs) if min_cluster_abs is not None and min_cluster_abs > 0 else None
    for entry in catalog_list:
        freq = int(entry["frequency"])
        rel = freq / total_comments
        big_by_freq = min_cluster_frequency <= 0 or rel >= min_cluster_frequency
        big_by_abs = abs_thr is None or freq >= abs_thr
        if big_by_freq and big_by_abs:
            main_entries.append(entry)
        else:
            rare = dict(entry)
            rare["is_outlier"] = True
            rare_entries.append(rare)

    out: dict[str, Any] = {
        "meta": {
            "total_notebooks": unique_notebooks,
            "total_source_comments": len(review_rows),
            "total_clusters": len(main_entries),
            "total_rare_patterns": len(rare_entries),
            "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "method": method,
            "auto_k_method": auto_k_method if method == "tfidf_kmeans" else None,
            "min_cluster_frequency": min_cluster_frequency,
            "min_cluster_abs": min_cluster_abs,
            "note_en": NON_AUTHORITY_NOTE_EN,
            "note_ru": NON_AUTHORITY_NOTE_RU,
            "source_project": source_project,
        },
        "catalog": main_entries,
        "rare_patterns": rare_entries,
    }
    if include_student and student_samples:
        out["student_context_samples"] = student_samples[:500]
        out["meta"]["student_context_sample_count"] = len(student_samples)
    return out


def write_catalog_json(catalog: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def catalog_to_markdown(catalog: dict[str, Any]) -> str:
    """Human-readable справочник."""
    meta = catalog.get("meta") or {}
    lines = [
        "# Справочник типичных комментариев ревьюера",
        "",
        f"_{meta.get('note_ru', NON_AUTHORITY_NOTE_RU)}_",
        "",
        f"_EN: {meta.get('note_en', NON_AUTHORITY_NOTE_EN)}_",
        "",
        f"- Сгенерировано: `{meta.get('generated_at', '')}`",
        f"- Метод кластеризации: `{meta.get('method', '')}`",
        f"- Исходных комментариев: **{meta.get('total_source_comments', 0)}**",
        f"- Кластеров: **{meta.get('total_clusters', 0)}**",
        "",
    ]
    current_sec = None
    for item in catalog.get("catalog") or []:
        sec = item.get("section") or "(без секции)"
        if sec != current_sec:
            current_sec = sec
            lines.append(f"## Секция: {sec}")
            lines.append("")
        col = item.get("alert_color", "unknown")
        lines.append(f"### Цвет / уровень: `{col}` — кластер `{item.get('cluster_id')}` (n={item.get('frequency')})")
        lines.append("")
        lines.append(f"**Типичная формулировка:** {item.get('representative_text', '')[:2000]}")
        if item.get("criterion_code"):
            lines.append("")
            lines.append(f"*Критерий (если задан в ноутбуке):* `{item['criterion_code']}`")
        lines.append("")
        lines.append("| Ноутбуки |")
        lines.append("|---|")
        nbs = item.get("source_notebooks") or []
        lines.append("| " + ", ".join(nbs[:15]) + (" …" if len(nbs) > 15 else "") + " |")
        lines.append("")
    rare = catalog.get("rare_patterns") or []
    if rare:
        lines.append("## Редкие / нетипичные паттерны")
        lines.append("")
        for item in rare:
            lines.append(
                f"### `{item.get('cluster_id')}` (n={item.get('frequency')}, outlier)"
            )
            lines.append("")
            lines.append(f"**Формулировка:** {item.get('representative_text', '')[:2000]}")
            lines.append("")
    return "\n".join(lines)
