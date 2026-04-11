from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from app.config import Settings


@dataclass
class PolicyDecision:
    action: int
    metadata: dict[str, Any] = field(default_factory=dict)


class RandomPolicy:
    def __init__(self, rng: random.Random | None = None):
        self._rng = rng or random.Random()

    def choose_action(
        self,
        observation: dict[str, Any],
        actions_count: int,
        context: dict[str, Any],
        *,
        gym_raw_obs: Any | None = None,
    ) -> PolicyDecision:
        if actions_count <= 0:
            raise ValueError("actions_count must be positive")
        action = self._rng.randrange(0, actions_count)
        return PolicyDecision(action=action, metadata={"strategy": "uniform_random"})


class OpenAIPolicy:
    """Minimal OpenAI-compatible policy for discrete action spaces."""

    def __init__(self, settings: Settings):
        self._settings = settings

    @property
    def _base_url(self) -> str:
        return (self._settings.rl_openai_base_url or self._settings.llm_base_url or "https://api.openai.com/v1").rstrip("/")

    @property
    def _api_key(self) -> str | None:
        return self._settings.rl_openai_api_key or self._settings.llm_api_key

    @property
    def _model(self) -> str:
        return self._settings.rl_openai_model or self._settings.llm_model

    def choose_action(
        self,
        observation: dict[str, Any],
        actions_count: int,
        context: dict[str, Any],
        *,
        gym_raw_obs: Any | None = None,
    ) -> PolicyDecision:
        api_key = self._api_key
        if not api_key or not api_key.strip():
            raise RuntimeError("RL OpenAI policy is not configured: API key is missing")
        if actions_count <= 0:
            raise ValueError("actions_count must be positive")

        prompt = {
            "instruction": (
                "Choose exactly one discrete action for an RL step. "
                "Return only compact JSON: {\"action\": <int>, \"reason\": \"...\"}."
            ),
            "actions_count": actions_count,
            "observation": observation,
            "policy_context": context,
        }
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [{"role": "user", "content": json.dumps(prompt, ensure_ascii=False)}],
            "temperature": 0.0,
        }
        url = f"{self._base_url}/chat/completions"
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        with httpx.Client(timeout=45.0) as client:
            response = client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
        raw = (data.get("choices") or [{}])[0].get("message", {}).get("content") or "{}"

        try:
            parsed = json.loads(str(raw).strip())
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"OpenAI policy returned non-JSON response: {raw}") from exc

        action = int(parsed.get("action", -1))
        if action < 0 or action >= actions_count:
            raise RuntimeError(f"OpenAI policy produced invalid action: {action}")
        return PolicyDecision(
            action=action,
            metadata={
                "model": self._model,
                "provider": "openai",
                "reason": str(parsed.get("reason", ""))[:200],
            },
        )


class SB3Policy:
    """Policy loaded from a Stable-Baselines3 checkpoint (``.zip``)."""

    def __init__(self, *, model_path: Path):
        from app.rl.sb3_io import load_sb3_model

        self._model = load_sb3_model(model_path)

    def choose_action(
        self,
        observation: dict[str, Any],
        actions_count: int,
        context: dict[str, Any],
        *,
        gym_raw_obs: Any | None = None,
    ) -> PolicyDecision:
        if gym_raw_obs is None:
            raise RuntimeError("SB3 policy requires gym_raw_obs from a Gymnasium environment step")
        action_arr, _states = self._model.predict(gym_raw_obs, deterministic=True)
        try:
            action = int(action_arr.item() if hasattr(action_arr, "item") else int(action_arr))
        except (TypeError, ValueError) as exc:
            raise RuntimeError(f"SB3 predict returned non-scalar action: {action_arr!r}") from exc
        if action < 0 or action >= actions_count:
            raise RuntimeError(f"SB3 produced invalid action {action} for n={actions_count}")
        return PolicyDecision(
            action=action,
            metadata={"strategy": "stable_baselines3", "deterministic": "true"},
        )
