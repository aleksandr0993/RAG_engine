from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass
class LLMClassificationResult:
    """Structured outcome of classify_text."""

    label: Literal["pass", "warn", "fail", "unknown"]
    confidence: float
    evidence: str = ""
    rationale: str = ""
    raw_response: dict[str, Any] = field(default_factory=dict)


@dataclass
class LLMCallResult:
    """Wrapper for any LLM invocation (success or graceful failure)."""

    ok: bool
    text: str = ""
    error: str | None = None
    provider: str = "none"
    model: str = ""
