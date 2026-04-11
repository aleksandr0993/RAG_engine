from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any

import httpx


@dataclass
class StepResult:
    observation: dict[str, Any]
    reward: float
    done: bool
    info: dict[str, Any]


class ToyBanditEnvironment:
    """Simple stochastic multi-armed bandit for experiments."""

    def __init__(self, arm_means: list[float], rng: random.Random | None = None):
        if not arm_means:
            raise ValueError("toy_bandit_arms must not be empty")
        self._arm_means = [max(0.0, min(1.0, float(x))) for x in arm_means]
        self._rng = rng or random.Random()
        self._steps = 0
        self._max_steps = 1

    @property
    def actions_count(self) -> int:
        return len(self._arm_means)

    def reset(self, max_steps: int) -> dict[str, Any]:
        self._steps = 0
        self._max_steps = max(1, max_steps)
        return {
            "env": "toy_bandit",
            "arm_means": self._arm_means,
            "remaining_steps": self._max_steps,
        }

    def step(self, action: int) -> StepResult:
        if action < 0 or action >= self.actions_count:
            raise ValueError(f"Action out of range: {action}")
        self._steps += 1
        prob = self._arm_means[action]
        reward = 1.0 if self._rng.random() <= prob else 0.0
        done = self._steps >= self._max_steps
        return StepResult(
            observation={
                "last_action": action,
                "remaining_steps": max(0, self._max_steps - self._steps),
            },
            reward=reward,
            done=done,
            info={"arm_mean": prob},
        )


class OpenSourceHttpEnvironment:
    """
    Adapter for open-source RL env APIs with reset/step endpoints.
    Expected reset JSON:
      {"observation": {...}, "actions_count": <int optional>}
    Expected step JSON:
      {"observation": {...}, "reward": <float>, "done": <bool>, "info": {... optional}}
    """

    def __init__(self, *, base_url: str, reset_path: str, step_path: str, timeout_sec: float):
        self._base_url = base_url.rstrip("/")
        self._reset_path = reset_path
        self._step_path = step_path
        self._timeout_sec = timeout_sec
        self._actions_count = 2

    @property
    def actions_count(self) -> int:
        return self._actions_count

    def reset(self, max_steps: int) -> dict[str, Any]:
        payload = {"max_steps": max_steps}
        with httpx.Client(timeout=self._timeout_sec) as client:
            resp = client.post(f"{self._base_url}{self._reset_path}", json=payload)
            resp.raise_for_status()
            data = resp.json()
        obs = data.get("observation") or {}
        actions_count = int(data.get("actions_count") or self._actions_count)
        self._actions_count = max(1, actions_count)
        return dict(obs)

    def step(self, action: int) -> StepResult:
        with httpx.Client(timeout=self._timeout_sec) as client:
            resp = client.post(f"{self._base_url}{self._step_path}", json={"action": action})
            resp.raise_for_status()
            data = resp.json()
        return StepResult(
            observation=dict(data.get("observation") or {}),
            reward=float(data.get("reward") or 0.0),
            done=bool(data.get("done")),
            info=dict(data.get("info") or {}),
        )
