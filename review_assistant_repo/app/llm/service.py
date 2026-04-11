from __future__ import annotations

from functools import lru_cache
from typing import Any

from app.config import get_settings
from app.llm.client import LLMClient
from app.llm.types import LLMCallResult, LLMClassificationResult


class LLMService:
    """Thin facade over LLMClient for analyzers and review pipeline."""

    def __init__(self, client: LLMClient | None = None):
        self._client = client or LLMClient()

    @property
    def is_available(self) -> bool:
        return self._client.enabled

    @property
    def semantic_checks_enabled(self) -> bool:
        return bool(get_settings().enable_llm_semantic_checks and self._client.enabled)

    def classify_text(self, task: str, text: str, context: dict[str, Any] | None = None) -> LLMClassificationResult:
        if not self.semantic_checks_enabled:
            return LLMClassificationResult(
                label="unknown",
                confidence=0.0,
                rationale="llm_semantic_checks_disabled",
                raw_response={"skipped": True},
            )
        return self._client.classify_text(task, text, context)

    def generate_comment(self, context: dict[str, Any]) -> str:
        return self._client.generate_comment(context)

    def synthesize_review(self, context: dict[str, Any]) -> str:
        if not get_settings().enable_llm:
            return context.get("fallback_review", "")
        return self._client.synthesize_review(context)

    def chat(self, messages: list[dict[str, str]], temperature: float = 0.2) -> LLMCallResult:
        return self._client.chat(messages, temperature=temperature)


@lru_cache(maxsize=1)
def get_llm_service() -> LLMService:
    return LLMService()
