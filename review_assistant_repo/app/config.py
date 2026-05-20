from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "dev"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    database_url: str = "sqlite:///./data/review_assistant.db"
    files_root: str = "./data/files"
    exports_root: str = "./data/exports"
    max_upload_bytes: int = 100 * 1024 * 1024
    default_style_profile: str = "practicum_review_requirements_v1"
    enable_browser_capture: bool = False
    browser_capture_timeout_ms: int = 15000
    capture_pool_workers: int = 2
    capture_pool_timeout_sec: float = 120.0
    capture_use_pool: bool = True
    datalens_settle_after_load_ms: int = 450
    datalens_tab_settle_ms: int = 550
    datalens_max_tab_screenshots: int = 4
    datalens_url_allowlist_enabled: bool = True

    enable_llm: bool = False
    llm_provider: str = "openai"
    llm_api_key: str | None = None
    llm_model: str = "gpt-4o-mini"
    llm_base_url: str | None = None
    enable_llm_comment_generation: bool = False
    enable_llm_semantic_checks: bool = False
    llm_max_retries: int = 3
    llm_retry_min_wait_sec: float = 1.0
    llm_retry_max_wait_sec: float = 20.0
    llm_circuit_failure_threshold: int = 5
    llm_circuit_cooldown_sec: float = 60.0
    enable_notebook_memory: bool = False
    notebook_memory_model: str | None = None
    notebook_memory_max_input_chars: int = 240_000
    notebook_memory_max_output_tokens: int = 3000

    enable_rl_engine: bool = False
    rl_openai_api_key: str | None = None
    rl_openai_model: str = "gpt-4o-mini"
    rl_openai_base_url: str | None = None
    rl_models_root: str = "./data/rl_models"
    rl_train_max_timesteps: int = 500_000
    rl_train_max_concurrent: int = 2
    require_auth_for_rl_writes: bool = False
    # async train: "background_tasks" (API process) | "external_worker" (poll DB in scripts/run_rl_train_worker.py)
    rl_train_async_executor: str = "background_tasks"
    rl_train_worker_poll_sec: float = 1.5

    # DB migrations: if True, run `alembic upgrade head` on startup (falls back to create_all on error).
    use_alembic_migrations: bool = True

    enable_retrieval: bool = False
    review_examples_path: str | None = None
    # Optional JSONL from a senior reviewer’s reference Colab (stylistic anchors only; see prompts).
    enable_reviewer_reference_examples: bool = False
    reviewer_reference_examples_path: str | None = None
    # Merged JSONL or directory of JSONL files built from several master-review .ipynb (see scripts/).
    enable_project_review_training: bool = False
    project_review_training_path: str | None = None
    # When set, project-training JSONL rows must match this source_project unless the row’s source_project is empty (wildcard).
    project_review_training_filter_project: str | None = None
    # Optional JSONL memory learned from source -> human-reviewed notebook pairs; affects insertion position only.
    enable_reviewer_insertion_memory: bool = False
    reviewer_insertions_path: str | None = "./data/reviewer_insertions/games_preprocessing.jsonl"
    reviewer_insertion_min_score: float = 0.45

    # Student Q&A assistant (RAG over project artifacts + optional course KB on disk)
    student_assistant_enabled: bool = True
    student_course_kb_dir: str = "./data/course_kb"
    student_assistant_use_llm: bool = False
    student_assistant_project_boost: float = 1.35
    student_assistant_top_k: int = 8
    student_assistant_answer_sources: int = 3
    enable_external_knowledge: bool = False
    external_knowledge_path: str | None = None

    # Optional semantic / hybrid retrieval (see app/retrieval/embed_backend.py)
    enable_semantic_retrieval: bool = False
    embedding_model: str = "local"  # local | openai
    openai_embedding_model: str = "text-embedding-3-small"
    retrieval_index_dir: str = "./data/retrieval_index"
    retrieval_hybrid_alpha: float = 0.5  # weight on BM25 vs dense (1-alpha on dense)
    retrieval_use_faiss: bool = False  # if False, use sklearn NearestNeighbors

    # Supabase (optional auth + storage)
    supabase_jwt_secret: str | None = None  # HS256; optional
    supabase_jwks_url: str | None = None  # RS256; e.g. https://xxx.supabase.co/auth/v1/.well-known/jwks.json
    supabase_url: str | None = None
    supabase_service_role_key: str | None = None  # for server-side storage only; keep secret
    supabase_storage_bucket: str = "projects-files"
    require_auth_for_writes: bool = False
    # When true, all /api/v1/debug/* and /api/v1/projects/{id}/debug/* require a valid Supabase JWT.
    require_auth_for_debug_routes: bool = False

    # Finding quality policy (confidence calibration + manual-review hints)
    finding_policy_enabled: bool = True
    finding_min_confidence_for_required_fail: float = 0.55

    # Whole-pipeline wall budget (0 = disabled). Checked between major stages.
    review_pipeline_timeout_sec: float = 0.0

    # Execute student .ipynb with nbclient before static review (outputs inform checks + iteration fixes).
    enable_notebook_execution: bool = True
    notebook_execution_timeout_sec: float = 120.0

    # Structured JSON-ish log lines for review/capture events
    review_structured_logs: bool = True

    # DataLens Playwright: retries with exponential backoff for goto / tab clicks
    datalens_goto_max_retries: int = 3
    datalens_tab_click_max_retries: int = 2
    datalens_step_retry_base_ms: int = 400

    # Browser SPA on another origin: comma-separated origins (empty = CORS middleware off)
    cors_allowed_origins: str = ""
    cors_allow_credentials: bool = False

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
