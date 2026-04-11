from __future__ import annotations

import random

from app.config import Settings, get_settings
from app.rl.environments import OpenSourceHttpEnvironment, ToyBanditEnvironment
from app.rl.gymnasium_env import GymnasiumDiscreteEnvironment
from app.rl.paths import resolve_rl_artefact_under_root
from app.rl.policies import OpenAIPolicy, PolicyDecision, RandomPolicy, SB3Policy
from app.rl.schemas import EpisodeRunRequest, EpisodeRunResponse, EpisodeStepDTO


class RLExperimentEngine:
    def __init__(self, settings: Settings | None = None):
        self._settings = settings or get_settings()

    def ensure_enabled(self) -> None:
        if not self._settings.enable_rl_engine:
            raise RuntimeError("RL engine is disabled. Set ENABLE_RL_ENGINE=true to use this API.")

    def _build_environment(self, request: EpisodeRunRequest, rng: random.Random):
        if request.environment == "toy_bandit":
            return ToyBanditEnvironment(arm_means=request.toy_bandit_arms, rng=rng)
        if request.environment == "open_source_http":
            if request.open_source_env is None:
                raise ValueError("open_source_env is required for environment=open_source_http")
            cfg = request.open_source_env
            return OpenSourceHttpEnvironment(
                base_url=cfg.base_url,
                reset_path=cfg.reset_path,
                step_path=cfg.step_path,
                timeout_sec=cfg.timeout_sec,
            )
        if request.environment == "gymnasium_discrete":
            return GymnasiumDiscreteEnvironment(
                env_id=request.gymnasium_env_id,
                kwargs=dict(request.gymnasium_kwargs or {}),
                seed=request.seed,
            )
        raise ValueError(f"Unsupported environment: {request.environment}")

    def _build_policy(self, request: EpisodeRunRequest, rng: random.Random):
        if request.policy == "random":
            return RandomPolicy(rng=rng)
        if request.policy == "openai":
            return OpenAIPolicy(settings=self._settings)
        if request.policy == "sb3":
            if not request.sb3_model_path:
                raise ValueError("sb3_model_path is required for policy=sb3")
            path = resolve_rl_artefact_under_root(
                self._settings,
                request.sb3_model_path.strip(),
                require_exists=True,
            )
            return SB3Policy(model_path=path)
        raise ValueError(f"Unsupported policy: {request.policy}")

    def run_episode(self, request: EpisodeRunRequest) -> EpisodeRunResponse:
        self.ensure_enabled()
        rng = random.Random(request.seed)
        env = self._build_environment(request, rng=rng)
        policy = self._build_policy(request, rng=rng)

        try:
            observation = env.reset(max_steps=request.max_steps)
            total_reward = 0.0
            steps: list[EpisodeStepDTO] = []
            policy_traces: list[dict[str, str]] = []

            for idx in range(1, request.max_steps + 1):
                raw_obs = getattr(env, "gym_raw_observation", None)
                decision: PolicyDecision = policy.choose_action(
                    observation=observation,
                    actions_count=env.actions_count,
                    context=request.policy_context,
                    gym_raw_obs=raw_obs,
                )
                step = env.step(decision.action)
                total_reward += float(step.reward)
                steps.append(
                    EpisodeStepDTO(
                        step=idx,
                        action=decision.action,
                        reward=float(step.reward),
                        done=bool(step.done),
                        observation=step.observation,
                        info=step.info,
                    )
                )
                if decision.metadata:
                    policy_traces.append({k: str(v)[:250] for k, v in decision.metadata.items()})
                observation = step.observation
                if step.done:
                    break

            return EpisodeRunResponse(
                environment=request.environment,
                policy=request.policy,
                total_reward=round(total_reward, 4),
                steps=steps,
                metadata={
                    "seed": request.seed,
                    "executed_steps": len(steps),
                    "policy_traces": policy_traces,
                    "gymnasium_env_id": request.gymnasium_env_id
                    if request.environment == "gymnasium_discrete"
                    else None,
                    "note": (
                        "Experimental RL API for quick iteration; use as an integration surface "
                        "for OpenAI and open-source RL backends (Gymnasium + Stable-Baselines3 optional)."
                    ),
                },
            )
        finally:
            closer = getattr(env, "close", None)
            if callable(closer):
                closer()
