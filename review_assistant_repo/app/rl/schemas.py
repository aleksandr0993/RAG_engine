from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.rl.paths import normalize_artefact_filename


class OpenSourceEnvConfig(BaseModel):
    base_url: str = Field(description="Base URL of Open-source RL environment HTTP API")
    reset_path: str = "/reset"
    step_path: str = "/step"
    timeout_sec: float = 30.0


class EpisodeRunRequest(BaseModel):
    environment: Literal["toy_bandit", "open_source_http", "gymnasium_discrete"] = "toy_bandit"
    policy: Literal["random", "openai", "sb3"] = "random"
    max_steps: int = Field(default=8, ge=1, le=2000)
    seed: int | None = None
    # For toy_bandit only. Higher value means better expected reward.
    toy_bandit_arms: list[float] = Field(default_factory=lambda: [0.2, 0.5, 0.85])
    # For open_source_http environment only.
    open_source_env: OpenSourceEnvConfig | None = None
    # For gymnasium_discrete: Gymnasium env id (discrete actions), e.g. CartPole-v1.
    gymnasium_env_id: str = "CartPole-v1"
    gymnasium_kwargs: dict[str, Any] = Field(default_factory=dict)
    # For policy=sb3: file name under RL_MODELS_ROOT (e.g. my_run.zip).
    sb3_model_path: str | None = None
    # Extra context that may help policy decisions.
    policy_context: dict[str, Any] = Field(default_factory=dict)

    @field_validator("sb3_model_path")
    @classmethod
    def _normalize_sb3_name(cls, v: str | None) -> str | None:
        if v is None:
            return v
        return normalize_artefact_filename(v.strip())

    @model_validator(mode="after")
    def _validate_sb3_and_gymnasium(self) -> EpisodeRunRequest:
        if self.policy == "sb3":
            if not (self.sb3_model_path and str(self.sb3_model_path).strip()):
                raise ValueError("sb3_model_path is required when policy=sb3")
            if self.environment != "gymnasium_discrete":
                raise ValueError("policy=sb3 requires environment=gymnasium_discrete")
        return self


class EpisodeStepDTO(BaseModel):
    step: int
    action: int
    reward: float
    done: bool
    observation: dict[str, Any] = Field(default_factory=dict)
    info: dict[str, Any] = Field(default_factory=dict)


class EpisodeRunResponse(BaseModel):
    environment: str
    policy: str
    total_reward: float
    steps: list[EpisodeStepDTO] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class RLEngineHealthResponse(BaseModel):
    status: Literal["ok", "disabled"]
    enabled: bool
    available_policies: list[str] = Field(default_factory=list)
    available_environments: list[str] = Field(default_factory=list)
    gymnasium_available: bool = False
    stable_baselines3_available: bool = False
    rl_train_async_executor: str = "background_tasks"


class RLTrainRequest(BaseModel):
    env_id: str = "CartPole-v1"
    algorithm: Literal["ppo", "a2c", "dqn"] = "ppo"
    total_timesteps: int = Field(default=10_000, ge=100, le=2_000_000)
    seed: int | None = None
    artefact_name: str = Field(
        default="sb3_model",
        description="Saved as <name>.zip under RL_MODELS_ROOT (letters, digits, ._- only)",
    )
    gymnasium_kwargs: dict[str, Any] = Field(default_factory=dict)

    @field_validator("artefact_name")
    @classmethod
    def _normalize_artefact(cls, v: str) -> str:
        return normalize_artefact_filename(v)


class RLTrainResponse(BaseModel):
    saved_path: str
    env_id: str
    algorithm: str
    total_timesteps: int


class RLTrainAsyncAccepted(BaseModel):
    """202 Accepted — training runs in API BackgroundTasks or an external DB-polling worker."""

    job_id: str
    status: Literal["accepted"] = "accepted"
    message: str = (
        "Training queued. Poll GET /api/v1/rl/train/jobs/{job_id} for status."
    )


class RLTrainJobStatusResponse(BaseModel):
    job_id: str
    status: Literal["accepted", "running", "completed", "failed"]
    artefact_name: str
    env_id: str
    algorithm: str
    total_timesteps: int
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    result: RLTrainResponse | None = None
    error: str | None = None
