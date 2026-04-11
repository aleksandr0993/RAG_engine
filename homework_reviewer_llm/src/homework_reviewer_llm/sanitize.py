"""Деперсонализация и фильтрация сырых записей."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from typing import Iterable

from homework_reviewer_llm.schema import NormalizedRecord, RawHomeworkRecord

# Email, телефоны RU/межд., простые URL
_RE_EMAIL = re.compile(
    r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+",
    re.IGNORECASE,
)
_RE_PHONE = re.compile(
    r"(?:\+?7|8)?[\s\-]?\(?\d{3}\)?[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}\b|\b\d{3}[\s\-]?\d{3}[\s\-]?\d{4}\b",
)
_RE_URL = re.compile(r"https?://[^\s]+|www\.[^\s]+", re.IGNORECASE)


def normalize_unicode(text: str) -> str:
    return unicodedata.normalize("NFKC", text)


def redact_pii(text: str) -> str:
    t = _RE_EMAIL.sub("[EMAIL]", text)
    t = _RE_PHONE.sub("[PHONE]", t)
    t = _RE_URL.sub("[URL]", t)
    return t


def scrub_record(raw: RawHomeworkRecord) -> NormalizedRecord:
    return NormalizedRecord(
        id=raw.id,
        student_id=raw.student_id.strip(),
        assignment_id=raw.assignment_id.strip(),
        submission_text=redact_pii(normalize_unicode(raw.submission_text)).strip(),
        review_text=redact_pii(normalize_unicode(raw.review_text)).strip(),
        overall_score=float(raw.overall_score),
        task_type=raw.task_type,
        language=raw.language or "ru",
        reviewer_id=raw.reviewer_id,
        assignment_prompt=(
            redact_pii(normalize_unicode(raw.assignment_prompt)).strip()
            if raw.assignment_prompt
            else None
        ),
        rubric_text=(
            redact_pii(normalize_unicode(raw.rubric_text)).strip() if raw.rubric_text else None
        ),
        rubric_scores=dict(raw.rubric_scores) if raw.rubric_scores else None,
        revision_history=(
            redact_pii(normalize_unicode(raw.revision_history)).strip()
            if raw.revision_history
            else None
        ),
        student_profile=(
            redact_pii(normalize_unicode(raw.student_profile)).strip()
            if raw.student_profile
            else None
        ),
        extra=dict(raw.extra),
    )


def passes_quality_filters(
    rec: NormalizedRecord,
    *,
    min_submission_len: int = 50,
    min_review_len: int = 20,
) -> bool:
    if len(rec.submission_text) < min_submission_len:
        return False
    if len(rec.review_text) < min_review_len:
        return False
    return True


def dedupe_by_submission_hash(records: Iterable[NormalizedRecord]) -> list[NormalizedRecord]:
    seen: set[str] = set()
    out: list[NormalizedRecord] = []
    for r in records:
        payload = f"{r.student_id}\n{r.assignment_id}\n{r.submission_text[:2000]}".encode()
        key = hashlib.sha256(payload).hexdigest()
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out
