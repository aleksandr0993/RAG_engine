from __future__ import annotations

from typing import Any

from app.rl.environments import StepResult
from app.rl.obs_serde import observation_to_jsonable


def _import_gymnasium():
    try:
        import gymnasium as gym
    except ImportError as exc:
        raise RuntimeError(
            "gymnasium is not installed. Install: pip install -e '.[rl]'"
        ) from exc
    return gym


class GymnasiumDiscreteEnvironment:
    """Discrete-action Gymnasium env with JSON-serializable observations and optional step cap."""

    def __init__(self, *, env_id: str, kwargs: dict[str, Any] | None = None, seed: int | None = None):
        gym = _import_gymnasium()
        self._env = gym.make(env_id, **(kwargs or {}))
        space = self._env.action_space
        if not hasattr(space, "n"):
            self._env.close()
            raise ValueError(
                f"Environment {env_id!r} must have a discrete action space (e.g. CartPole-v1); got {type(space).__name__}"
            )
        self._n_actions: int = int(space.n)
        self._seed = seed
        self._step_idx = 0
        self._max_steps = 1
        self._last_raw_obs: Any = None

    @property
    def actions_count(self) -> int:
        return self._n_actions

    @property
    def gym_raw_observation(self) -> Any:
        return self._last_raw_obs

    def reset(self, max_steps: int) -> dict[str, Any]:
        self._step_idx = 0
        self._max_steps = max(1, int(max_steps))
        obs, _info = self._env.reset(seed=self._seed)
        self._last_raw_obs = obs
        out = observation_to_jsonable(obs)
        out["gymnasium_env_id"] = getattr(self._env.spec, "id", None) or ""
        out["remaining_steps"] = self._max_steps
        return out

    def step(self, action: int) -> StepResult:
        if action < 0 or action >= self._n_actions:
            raise ValueError(f"Action out of range: {action}")
        self._step_idx += 1
        obs, reward, terminated, truncated, info = self._env.step(action)
        self._last_raw_obs = obs
        done = bool(terminated or truncated or self._step_idx >= self._max_steps)
        return StepResult(
            observation=observation_to_jsonable(obs),
            reward=float(reward),
            done=done,
            info=dict(info or {}),
        )

    def close(self) -> None:
        self._env.close()
