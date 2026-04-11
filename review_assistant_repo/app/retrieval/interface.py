from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol


@dataclass
class ReviewExample:
    example_id: str
    criterion_code: str
    text: str
    tags: list[str]
    score: float = 1.0
    created_at: str | None = None  # optional ISO timestamp from JSONL for future decay weighting
    # True when loaded from reviewer_reference JSONL (senior Colab export); not ground truth.
    from_reviewer_reference: bool = False
    # Corpus lane: general | project_training | reviewer_reference
    source_kind: str = "general"
    # Role of the comment text in master-review notebooks / training JSONL (not authoritative).
    author_role: str = "unknown"  # reviewer | middle_reviewer | student | unknown
    source_project: str = ""
    source_notebook: str = ""
    student_context: str = ""
    section_name: str = ""


class RetrievalBackend(Protocol):
    def retrieve(
        self,
        query: str,
        criterion_code: str | None,
        limit: int = 3,
        *,
        filter_source_project: str | None = None,
        filter_section_name: str | None = None,
    ) -> Sequence[ReviewExample]:
        ...
