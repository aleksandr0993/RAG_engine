from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

AlgorithmName = Literal["ppo", "a2c", "dqn"]


def _import_sb3():
    try:
        from stable_baselines3 import A2C, DQN, PPO
    except ImportError as exc:
        raise RuntimeError(
            "stable-baselines3 is not installed. Install: pip install -e '.[rl,rl_sb3]'"
        ) from exc
    return A2C, DQN, PPO


def train_sb3(
    *,
    env_id: str,
    algorithm: AlgorithmName,
    total_timesteps: int,
    save_path: Path,
    seed: int | None = None,
    gymnasium_kwargs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Train a small SB3 agent and save to ``save_path`` (``.zip``)."""
    A2C, DQN, PPO = _import_sb3()
    import gymnasium as gym

    save_path = Path(save_path)
    save_path.parent.mkdir(parents=True, exist_ok=True)
    stem = save_path
    if stem.suffix.lower() == ".zip":
        stem = stem.with_suffix("")

    env = gym.make(env_id, **(gymnasium_kwargs or {}))
    try:
        algo_cls = {"ppo": PPO, "a2c": A2C, "dqn": DQN}[algorithm]
        model = algo_cls("MlpPolicy", env, verbose=0, seed=seed)
        model.learn(total_timesteps=int(total_timesteps))
        model.save(str(stem))
    finally:
        env.close()

    zip_path = Path(str(stem) + ".zip")
    return {
        "saved_path": str(zip_path),
        "env_id": env_id,
        "algorithm": algorithm,
        "total_timesteps": int(total_timesteps),
    }


def load_sb3_model(path: Path) -> Any:
    """Load a saved SB3 model (PPO / A2C / DQN)."""
    A2C, DQN, PPO = _import_sb3()
    path = Path(path)
    if path.suffix.lower() != ".zip":
        path = path.with_suffix(".zip")
    stem = str(path.with_suffix(""))
    last_exc: Exception | None = None
    for cls in (PPO, A2C, DQN):
        try:
            return cls.load(stem)
        except Exception as exc:
            last_exc = exc
            continue
    raise RuntimeError(f"Could not load SB3 model from {path}: {last_exc}") from last_exc
