from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import httpx
from tenacity import RetryError, retry, retry_if_exception, stop_after_attempt, wait_exponential

from app.config import Settings, get_settings
from app.llm.circuit import is_circuit_open, record_failure, record_success
from app.llm.types import LLMCallResult, LLMClassificationResult


def _retryable_http_error(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        return code == 429 or code >= 500
    return False


def _load_prompt_file(name: str) -> str:
    path = Path(__file__).resolve().parent / "prompts" / name
    return path.read_text(encoding="utf-8")


def _extract_json_object(text: str) -> dict[str, Any] | None:
    text = text.strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    return None


class LLMClient:
    """OpenAI-compatible chat completions client with hard fallback when disabled."""

    def __init__(self, settings: Settings | None = None):
        self._settings = settings or get_settings()

    @property
    def enabled(self) -> bool:
        s = self._settings
        return bool(s.enable_llm and s.llm_api_key and s.llm_api_key.strip())

    @property
    def base_url(self) -> str:
        return (self._settings.llm_base_url or "https://api.openai.com/v1").rstrip("/")

    def _post_chat_once(
        self,
        url: str,
        headers: dict[str, str],
        body: dict[str, Any],
    ) -> str:
        with httpx.Client(timeout=120.0) as client:
            resp = client.post(url, headers=headers, json=body)
            resp.raise_for_status()
            data = resp.json()
        content = (data.get("choices") or [{}])[0].get("message", {}).get("content") or ""
        return str(content).strip()

    def _chat(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.2,
        *,
        model: str | None = None,
        max_tokens: int | None = None,
    ) -> LLMCallResult:
        if not self.enabled:
            return LLMCallResult(ok=False, error="llm_disabled", provider=self._settings.llm_provider, model=self._settings.llm_model)

        if is_circuit_open(self._settings):
            return LLMCallResult(
                ok=False,
                error="llm_circuit_open",
                provider=self._settings.llm_provider,
                model=self._settings.llm_model,
            )

        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._settings.llm_api_key}",
            "Content-Type": "application/json",
        }
        body: dict[str, Any] = {
            "model": model or self._settings.llm_model,
            "messages": messages,
            "temperature": temperature,
        }
        if max_tokens is not None:
            body["max_tokens"] = int(max_tokens)

        attempts = max(1, int(self._settings.llm_max_retries))

        @retry(
            stop=stop_after_attempt(attempts),
            wait=wait_exponential(
                multiplier=1,
                min=self._settings.llm_retry_min_wait_sec,
                max=self._settings.llm_retry_max_wait_sec,
            ),
            retry=retry_if_exception(_retryable_http_error),
            reraise=True,
        )
        def _do() -> str:
            return self._post_chat_once(url, headers, body)

        try:
            text = _do()
            record_success()
            return LLMCallResult(
                ok=True,
                text=text,
                provider=self._settings.llm_provider,
                model=str(body["model"]),
            )
        except httpx.HTTPStatusError as exc:
            code = exc.response.status_code
            if code == 429 or code >= 500:
                record_failure(self._settings)
            return LLMCallResult(
                ok=False,
                error=f"HTTPStatusError:{code}:{exc}",
                provider=self._settings.llm_provider,
                model=self._settings.llm_model,
            )
        except RetryError as exc:
            last = exc.last_attempt.exception()
            if isinstance(last, httpx.HTTPStatusError):
                code = last.response.status_code
                if code == 429 or code >= 500:
                    record_failure(self._settings)
                return LLMCallResult(
                    ok=False,
                    error=f"HTTPStatusError:{code}:{last}",
                    provider=self._settings.llm_provider,
                    model=self._settings.llm_model,
                )
            record_failure(self._settings)
            return LLMCallResult(
                ok=False,
                error=f"{type(last).__name__}:{last}",
                provider=self._settings.llm_provider,
                model=self._settings.llm_model,
            )
        except Exception as exc:
            record_failure(self._settings)
            return LLMCallResult(
                ok=False,
                error=f"{type(exc).__name__}:{exc}",
                provider=self._settings.llm_provider,
                model=self._settings.llm_model,
            )

    def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.2,
        *,
        model: str | None = None,
        max_tokens: int | None = None,
    ) -> LLMCallResult:
        """OpenAI-compatible chat; same availability rules as other LLM calls."""
        return self._chat(messages, temperature, model=model, max_tokens=max_tokens)

    def classify_text(self, task: str, text: str, context: dict[str, Any] | None = None) -> LLMClassificationResult:
        """
        Classify `text` for `task` using the classify_task prompt template.
        Always returns a structured result; on failure uses unknown + low confidence.
        """
        ctx = context or {}
        prompt = _load_prompt_file("classify_task.txt").format(
            task=task,
            context=json.dumps(ctx, ensure_ascii=False)[:4000],
            text=(text or "")[:8000],
        )
        result = self._chat([{"role": "user", "content": prompt}], temperature=0.1)
        if not result.ok:
            return LLMClassificationResult(
                label="unknown",
                confidence=0.25,
                evidence="",
                rationale=result.error or "llm_unavailable",
                raw_response={"llm_error": result.error},
            )

        parsed = _extract_json_object(result.text)
        if not parsed:
            return LLMClassificationResult(
                label="unknown",
                confidence=0.3,
                evidence=result.text[:200],
                rationale="unparseable_llm_response",
                raw_response={"raw": result.text[:500]},
            )

        label = str(parsed.get("label", "unknown")).lower()
        if label not in {"pass", "warn", "fail", "unknown"}:
            label = "unknown"
        try:
            confidence = float(parsed.get("confidence", 0.5))
        except (TypeError, ValueError):
            confidence = 0.5
        confidence = max(0.0, min(1.0, confidence))

        return LLMClassificationResult(
            label=label,  # type: ignore[arg-type]
            confidence=confidence,
            evidence=str(parsed.get("evidence", ""))[:500],
            rationale=str(parsed.get("rationale", ""))[:500],
            raw_response=parsed,
        )

    def generate_comment(self, context: dict[str, Any]) -> str:
        """Return improved Russian comment or fall back to template/body from context."""
        if not self._settings.enable_llm_comment_generation or not self.enabled:
            return context.get("template") or context.get("body") or ""

        retrieval = context.get("retrieval_examples") or []
        prompt = _load_prompt_file("generate_comment.txt").format(
            title=context.get("title", ""),
            description=context.get("description", ""),
            template=context.get("template", ""),
            evidence=json.dumps(context.get("evidence", []), ensure_ascii=False)[:3000],
            style_profile=json.dumps(context.get("style_profile", {}), ensure_ascii=False)[:5000],
            project_memory=json.dumps(context.get("project_memory", []), ensure_ascii=False)[:5000],
            retrieval_examples=json.dumps(retrieval, ensure_ascii=False)[:4000],
        )
        result = self._chat([{"role": "user", "content": prompt}], temperature=0.35)
        if not result.ok or not result.text:
            return context.get("template") or ""
        if "USE_TEMPLATE" in result.text.upper():
            return context.get("template") or ""
        return result.text.strip()

    def synthesize_review(self, context: dict[str, Any]) -> str:
        """Polish review text; returns fallback_review from context if LLM off or fails."""
        fallback = context.get("fallback_review") or ""
        if not self.enabled:
            return fallback

        prompt = _load_prompt_file("synthesize_review.txt").format(
            sections=json.dumps(context.get("sections", {}), ensure_ascii=False)[:12000],
            style_profile=json.dumps(context.get("style_profile", {}), ensure_ascii=False)[:5000],
        )
        result = self._chat([{"role": "user", "content": prompt}], temperature=0.3)
        if not result.ok or not result.text:
            return fallback
        return result.text.strip()
