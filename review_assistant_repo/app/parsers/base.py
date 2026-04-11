from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ParsedArtifact:
    artifact_type: str
    position_idx: int | None
    raw_text: str | None
    normalized_text: str | None
    section_name: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
