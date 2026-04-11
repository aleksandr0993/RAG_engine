from __future__ import annotations

import json
from dataclasses import replace
from functools import lru_cache
from pathlib import Path

from app.config import get_settings
from app.retrieval.interface import RetrievalBackend, ReviewExample


def _iter_jsonl_rows(path: Path) -> list[dict]:
    rows: list[dict] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    except (OSError, json.JSONDecodeError):
        return []
    return rows


def _project_training_jsonl_paths(base: Path) -> list[Path]:
    if base.is_file() and base.suffix.lower() == ".jsonl":
        return [base]
    if base.is_dir():
        return sorted(base.glob("*.jsonl"))
    return []


def _normalize_author_role(raw: str | None) -> str:
    role = (raw or "unknown").strip().lower()
    if role in ("reviewer", "middle_reviewer", "student", "unknown"):
        return role
    return "unknown"


def _normalize_source_kind(raw: str) -> str:
    k = (raw or "general").strip().lower()
    if k in ("general", "project_training", "reviewer_reference"):
        return k
    return "general"


def _row_matches_criterion(row: dict, criterion_code: str | None) -> bool:
    if not criterion_code:
        return True
    cc = str(row.get("criterion_code") or "").strip()
    if not cc:
        return True
    return cc == criterion_code


def _row_matches_source_project(row: dict, filter_source_project: str | None) -> bool:
    """Row with empty source_project matches any filter (wildcard)."""
    if not filter_source_project or not str(filter_source_project).strip():
        return True
    want = str(filter_source_project).strip()
    got = str(row.get("source_project") or "").strip()
    if not got:
        return True
    return got == want


def _row_to_example(row: dict, *, source_kind: str) -> ReviewExample | None:
    text = (row.get("text") or "").strip()
    if not text:
        return None
    role = _normalize_author_role(row.get("author_role"))
    raw_sk = row.get("source_kind")
    if isinstance(raw_sk, str) and raw_sk.strip():
        sk = _normalize_source_kind(raw_sk)
    else:
        sk = _normalize_source_kind(source_kind)
    return ReviewExample(
        example_id=str(row.get("example_id", "")),
        criterion_code=str(row.get("criterion_code") or ""),
        text=text,
        tags=list(row.get("tags") or []),
        score=float(row.get("score", 1.0)),
        from_reviewer_reference=(sk == "reviewer_reference"),
        source_kind=sk,
        author_role=role,
        source_project=str(row.get("source_project") or ""),
        source_notebook=str(row.get("source_notebook") or ""),
        student_context=str(row.get("student_context") or "")[:4000],
        section_name=str(row.get("section_name") or ""),
    )


def _sort_pt_by_section(examples: list[ReviewExample], filter_section_name: str | None) -> list[ReviewExample]:
    if not filter_section_name or not str(filter_section_name).strip():
        return list(examples)
    f = str(filter_section_name).strip()

    def sort_key(ex: ReviewExample) -> tuple[int, str]:
        s = (ex.section_name or "").strip()
        if s == f:
            return (0, ex.example_id)
        if not s:
            return (1, ex.example_id)
        return (2, ex.example_id)

    return sorted(examples, key=sort_key)


def _pick_diverse_by_notebook(examples: list[ReviewExample], cap: int) -> list[ReviewExample]:
    """Prefer at most one example per source_notebook, then fill remaining slots."""
    if cap <= 0:
        return []
    picked: list[ReviewExample] = []
    seen_keys: set[tuple[str, str]] = set()
    per_nb: dict[str, int] = {}

    def key(ex: ReviewExample) -> tuple[str, str]:
        return (ex.example_id, ex.text[:120])

    # First pass: at most one per notebook
    for ex in examples:
        if len(picked) >= cap:
            break
        k = key(ex)
        if k in seen_keys:
            continue
        nb = ex.source_notebook or "_default"
        if per_nb.get(nb, 0) >= 1:
            continue
        picked.append(ex)
        seen_keys.add(k)
        per_nb[nb] = 1

    # Second pass: fill without per-notebook cap
    if len(picked) < cap:
        for ex in examples:
            if len(picked) >= cap:
                break
            k = key(ex)
            if k in seen_keys:
                continue
            picked.append(ex)
            seen_keys.add(k)

    return picked


def _allocate_caps(
    *,
    limit: int,
    has_pt: bool,
    has_ref: bool,
    has_gen: bool,
) -> tuple[int, int, int]:
    """Return (cap_pt, cap_ref, cap_gen)."""
    n = limit
    if has_pt and has_gen and has_ref:
        cap_pt = min(2, n)
        cap_ref = min(1, max(0, n - cap_pt))
        cap_gen = max(0, n - cap_pt - cap_ref)
        return cap_pt, cap_ref, cap_gen
    if has_pt and has_gen:
        cap_pt = min(2, n)
        return cap_pt, 0, n - cap_pt
    if has_pt and has_ref:
        cap_pt = min(2, n)
        return cap_pt, n - cap_pt, 0
    if has_ref and has_gen:
        cap_ref = min(1, n)
        return 0, cap_ref, n - cap_ref
    if has_pt:
        return n, 0, 0
    if has_ref:
        return 0, n, 0
    return 0, 0, n


class LocalFileRetrievalBackend:
    """
    JSONL-backed retrieval: one object per line with keys
    example_id, criterion_code, text, tags (optional), score (optional),
    author_role, source_project, source_notebook, student_context, section_name (optional),
    source_kind (optional override: general | project_training | reviewer_reference).

    Sources (when enabled): project master-review corpus (file or dir of JSONL),
    legacy reviewer_reference file, general corpus (substring match on query).
    """

    def __init__(self, path: Path | None = None):
        settings = get_settings()
        self.path = path or (Path(settings.review_examples_path) if settings.review_examples_path else None)

    def retrieve(
        self,
        query: str,
        criterion_code: str | None,
        limit: int = 3,
        *,
        filter_source_project: str | None = None,
        filter_section_name: str | None = None,
    ) -> list[ReviewExample]:
        settings = get_settings()
        if not settings.enable_retrieval or limit <= 0:
            return []

        q = (query or "").lower()

        proj_filter = (filter_source_project or "").strip()
        if not proj_filter:
            proj_filter = (settings.project_review_training_filter_project or "").strip()
        proj_filter_use = proj_filter or None

        pt_rows: list[dict] = []
        if settings.enable_project_review_training and settings.project_review_training_path:
            base = Path(settings.project_review_training_path)
            for fp in _project_training_jsonl_paths(base):
                pt_rows.extend(_iter_jsonl_rows(fp))

        ref_path: Path | None = None
        if settings.enable_reviewer_reference_examples and settings.reviewer_reference_examples_path:
            p = Path(settings.reviewer_reference_examples_path)
            if p.is_file():
                ref_path = p

        has_general = self.path is not None and self.path.is_file()
        has_ref = ref_path is not None
        has_pt = bool(pt_rows)

        if not has_general and not has_ref and not has_pt:
            return []

        cap_pt, cap_ref, _cap_gen = _allocate_caps(
            limit=limit, has_pt=has_pt, has_ref=has_ref, has_gen=has_general
        )

        out: list[ReviewExample] = []
        seen: set[tuple[str, str]] = set()

        def add_unique(ex: ReviewExample) -> bool:
            k = (ex.example_id, ex.text[:200])
            if k in seen:
                return False
            seen.add(k)
            out.append(ex)
            return True

        # Project training: reviewer / middle_reviewer only; optional criterion & source_project
        if cap_pt:
            pt_candidates: list[ReviewExample] = []
            for row in pt_rows:
                if not _row_matches_criterion(row, criterion_code):
                    continue
                if not _row_matches_source_project(row, proj_filter_use):
                    continue
                role = _normalize_author_role(row.get("author_role"))
                if role == "student":
                    continue
                ex = _row_to_example(row, source_kind="project_training")
                if ex:
                    pt_candidates.append(ex)
            pt_candidates = _sort_pt_by_section(pt_candidates, filter_section_name)
            for ex in _pick_diverse_by_notebook(pt_candidates, cap_pt):
                if len(out) >= cap_pt:
                    break
                add_unique(ex)

        # Legacy senior reference JSONL
        if cap_ref and ref_path is not None:
            ref_budget = min(cap_ref, max(0, limit - len(out)))
            ref_added = 0
            for row in _iter_jsonl_rows(ref_path):
                if ref_added >= ref_budget or len(out) >= limit:
                    break
                if criterion_code and row.get("criterion_code") != criterion_code:
                    continue
                ex = _row_to_example(row, source_kind="reviewer_reference")
                if ex is None:
                    continue
                if ex.author_role == "unknown":
                    ex = replace(ex, author_role="reviewer")
                if add_unique(ex):
                    ref_added += 1

        # General corpus (substring); fill remaining slots up to limit
        if self.path is not None and self.path.is_file():
            for row in _iter_jsonl_rows(self.path):
                if len(out) >= limit:
                    break
                if criterion_code and row.get("criterion_code") != criterion_code:
                    continue
                text = row.get("text") or ""
                if q and q not in text.lower():
                    continue
                ex = _row_to_example(row, source_kind="general")
                if ex is None:
                    continue
                add_unique(ex)

        return out[:limit]


def gather_retrieval_pool(
    *,
    backend: LocalFileRetrievalBackend | None = None,
    criterion_code: str | None,
    filter_source_project: str | None = None,
    filter_section_name: str | None = None,
    max_pool: int = 800,
) -> list[ReviewExample]:
    """
    Collect up to ``max_pool`` examples matching filters, without lexical query gating on the general corpus.
    Used by hybrid / semantic retrieval to score a fixed candidate pool.
    """
    settings = get_settings()
    b = backend or LocalFileRetrievalBackend()

    proj_filter = (filter_source_project or "").strip()
    if not proj_filter:
        proj_filter = (settings.project_review_training_filter_project or "").strip()
    proj_filter_use = proj_filter or None

    pt_rows: list[dict] = []
    if settings.enable_project_review_training and settings.project_review_training_path:
        base = Path(settings.project_review_training_path)
        for fp in _project_training_jsonl_paths(base):
            pt_rows.extend(_iter_jsonl_rows(fp))

    ref_path: Path | None = None
    if settings.enable_reviewer_reference_examples and settings.reviewer_reference_examples_path:
        p = Path(settings.reviewer_reference_examples_path)
        if p.is_file():
            ref_path = p

    has_general = b.path is not None and b.path.is_file()
    has_ref = ref_path is not None
    has_pt = bool(pt_rows)

    if not has_general and not has_ref and not has_pt:
        return []

    pool: list[ReviewExample] = []
    seen: set[tuple[str, str]] = set()

    def add_unique(ex: ReviewExample) -> None:
        if len(pool) >= max_pool:
            return
        k = (ex.example_id, ex.text[:200])
        if k in seen:
            return
        seen.add(k)
        pool.append(ex)

    if has_pt:
        pt_candidates: list[ReviewExample] = []
        for row in pt_rows:
            if not _row_matches_criterion(row, criterion_code):
                continue
            if not _row_matches_source_project(row, proj_filter_use):
                continue
            role = _normalize_author_role(row.get("author_role"))
            if role == "student":
                continue
            ex = _row_to_example(row, source_kind="project_training")
            if ex:
                pt_candidates.append(ex)
        for ex in _sort_pt_by_section(pt_candidates, filter_section_name):
            if len(pool) >= max_pool:
                break
            add_unique(ex)

    if has_ref and ref_path is not None and len(pool) < max_pool:
        for row in _iter_jsonl_rows(ref_path):
            if len(pool) >= max_pool:
                break
            if criterion_code and row.get("criterion_code") != criterion_code:
                continue
            ex = _row_to_example(row, source_kind="reviewer_reference")
            if ex is None:
                continue
            if ex.author_role == "unknown":
                ex = replace(ex, author_role="reviewer")
            add_unique(ex)

    if has_general and b.path is not None and b.path.is_file() and len(pool) < max_pool:
        for row in _iter_jsonl_rows(b.path):
            if len(pool) >= max_pool:
                break
            if criterion_code and row.get("criterion_code") != criterion_code:
                continue
            ex = _row_to_example(row, source_kind="general")
            if ex is None:
                continue
            add_unique(ex)

    return pool


@lru_cache(maxsize=1)
def get_retrieval_backend() -> RetrievalBackend:
    settings = get_settings()
    base = LocalFileRetrievalBackend()
    if settings.enable_semantic_retrieval:
        from app.retrieval.hybrid_backend import HybridRetrievalBackend

        return HybridRetrievalBackend(base)
    return base
