# Changelog

## 0.9.10

- **Config / HTTP**: опциональный CORS (`CORS_ALLOWED_ORIGINS` — список через запятую; пусто = выкл.). Для ответов с `Origin` из списка в `Access-Control-Expose-Headers` отдаются `X-Total-Count`, `X-Total-Count-Truncated`, `X-Next-Cursor`. Флаг `CORS_ALLOW_CREDENTIALS`.

## 0.9.9

- **API**: `GET /api/v1/projects` — query `include_total` (по умолчанию `true`); при `false` не выполняется подсчёт для `X-Total-Count*`.
- **Итерации / качество метаданных**: нормализация `iteration_fix_summary`, `notebook_execution` и `detail_json` при ревью и бэкфилле; `GET /api/v1/debug/metadata_quality_audit`, `POST /api/v1/debug/metadata_backfill`; gauge/counter-метрики на `GET /api/v1/metrics`.
- **Безопасность**: `REQUIRE_AUTH_FOR_DEBUG_ROUTES=true` — для всех `GET/POST /api/v1/debug/*` и `GET /api/v1/projects/{id}/debug/*` нужен валидный Supabase JWT (`Authorization: Bearer` или `X-User-Token`), при настроенном `SUPABASE_JWT_SECRET` / `SUPABASE_JWKS_URL`.

## 0.9.8

- **API**: `GET /api/v1/projects` — keyset-пагинация: query `cursor`, заголовок `X-Next-Cursor` при наличии следующей страницы; стабильный порядок `created_at DESC, id DESC`. С `practicum_input_channel` keyset только на SQLite/PostgreSQL (иначе `422`).

## 0.9.7

- **API**: `GET /api/v1/projects` — заголовок `X-Total-Count` (и при необходимости `X-Total-Count-Truncated`) для UI-пагинации.

## 0.9.6

- **Документация**: в шапке README актуальная версия пакета.
- **API**: `GET /api/v1/debug/practicum_stats` — опциональный query `practicum_input_channel` (как у `GET /api/v1/projects`); в `filters` ответа добавлен ключ `practicum_input_channel`.

## 0.9.5

- **API**: `GET /api/v1/projects` — query `offset` (пагинация после сортировки по `created_at` desc).
- **API**: `GET /api/v1/debug/practicum_stats` — опциональные `source_type`, `status`; в ответе поле `filters`.

## 0.9.4

- **API**: `GET /api/v1/projects` — дополнительные query `source_type`, `status` (валидация значений).
- **API**: `GET /api/v1/debug/practicum_stats` — разрезы `by_source_type`, `by_project_status`, `by_final_verdict`.

## 0.9.3

- **Документация**: таблица ключей `metadata_json` (Практикум / Revisor HTML); примеры `curl` для `practicum_input_channel`, фильтра списка и `practicum_stats`.
- **API**: `GET /api/v1/projects?practicum_input_channel=` — фильтр по каналу (SQLite `json_extract`, PostgreSQL JSON path).
- **API**: `GET /api/v1/debug/practicum_stats` — сводка по каналам и `practicum_revisor_detection_confidence`.
- **Тесты**: golden e2e для HTML strong/medium/weak после ревью.
- **Релиз**: `RELEASE.md` с чеклистом и командами тега `v0.9.3`.

## 0.9.2

- **Revisor HTML**: многоуровневая детекция (`app/parsers/practicum_revisor_html.py`) — `practicum_revisor_detection_confidence`, `practicum_revisor_detection_reasons`, `practicum_revisor_score`; `practicum_revisor_html_detected` и апгрейд канала только для `medium`/`strong` (меньше ложных срабатываний на тексте без URL Практикума).

## 0.9.1

- **Практикум**: поле загрузки `practicum_input_channel` (`auto` / `jupyter` / `revisor`); в `metadata_json` — `practicum_input_channel`, `practicum_input_explicit`; HTML-парсер детектирует сохранённые страницы Практикума/Ревизора (`practicum_revisor_html_detected`, `source_flavor=practicum_revisor_html`) и при авто-канале `html` может обновить канал на `revisor` после ревью.

## 0.9.0

- **Quality core + foundation** (confidence policy, jobs, capture retries, observability, CI README check).
- **Findings policy**: unified `source_stage` coercion (`finding_policy.py`); required `fail` below confidence → `warn` + `manual_review_suggested`; required `unknown` flagged; `quality_summary` + `review_pipeline_timeline` in project `metadata_json`.
- **Config**: `FINDING_POLICY_ENABLED`, `FINDING_MIN_CONFIDENCE_FOR_REQUIRED_FAIL`, `REVIEW_PIPELINE_TIMEOUT_SEC`, `REVIEW_STRUCTURED_LOGS`, `DATALENS_GOTO_MAX_RETRIES`, `DATALENS_TAB_CLICK_MAX_RETRIES`, `DATALENS_STEP_RETRY_BASE_MS`.
- **Jobs**: durable `review_jobs` table (Alembic `b2c3d4e5f6a0`); `POST .../review/async` returns real `job_id`; `GET .../review/jobs/{job_id}`; idempotency — no concurrent `queued`/`running` job per project; sync `POST .../review` also blocked if an active job exists.
- **Capture**: DataLens `goto` / tab click retries with exponential backoff.
- **Observability**: structured review events (`app/utils/logging_json.py`); `GET /api/v1/debug/review_metrics` (p50/p95, low-confidence counter); `GET .../debug/review_timeline`.
- **Criteria summary**: `by_source_stage_status`, low-confidence / manual-review approx counts.
- **CI**: `scripts/check_readme_endpoints.py` README ↔ OpenAPI drift check.
- **Tests**: golden regression + finding policy + review job coverage.

## 0.8.9

- **LLM**: `tenacity` retries (429/5xx) + thread-safe circuit breaker (`app/llm/circuit.py`); settings `LLM_MAX_RETRIES`, `LLM_CIRCUIT_*`.
- **Reviews**: `POST /api/v1/projects/{id}/review/async` → **202** + FastAPI `BackgroundTasks`; WebSocket `/api/v1/ws/projects/{id}/status`; sync review returns **409** if already `processing`.
- **DB**: Alembic baseline (`alembic/`, `USE_ALEMBIC_MIGRATIONS`); `project_assignments` table + matching admin routes.
- **Health**: `/api/v1/health/ready` (DB ping + optional LLM key check); `/api/v1/metrics` (basic Prometheus text).
- **Catalog**: silhouette / sqrt / fixed auto-K for `tfidf_kmeans`; centroid-based representative; `rare_patterns` + `min_cluster_frequency` / `min_cluster_abs`; CLI flags `--auto-k-method`, `--min-cluster-frequency`, `--min-cluster-abs`.
- **Retrieval**: optional hybrid BM25 + dense (`ENABLE_SEMANTIC_RETRIEVAL`, `RETRIEVAL_HYBRID_ALPHA`, `app/retrieval/embed_backend.py`, `hybrid_backend.py`, `bm25_util.py`); `gather_retrieval_pool`; optional `created_at` on `ReviewExample`.
- **Supabase**: JWT decode (`app/auth/supabase_jwt.py`, `require_user_for_writes`); optional Storage mirror on upload (`app/storage/supabase_storage.py`).
- **API**: `GET /api/v1/projects` (list); admin `POST/GET .../admin/projects/{id}/assignments*`.
- **Frontend**: `frontend/` Next.js 14 app (dashboard, upload, project detail, catalog viewer, admin assignments, optional Supabase login).

## 0.8.8

- **Reviewer comment catalog**: офлайн-сборка справочника типичных комментариев из многих `.ipynb` — [`app/retrieval/comment_catalog.py`](app/retrieval/comment_catalog.py): кластеризация по `section_name` и цвету Bootstrap-алерта (`danger` / `warning` / `success`), методы `heuristic` (Jaccard) и опционально `tfidf_kmeans` (`pip install -e .[analysis]`); JSON + Markdown; дисклеймер «не рубрика / не ground truth».
- **CLI**: [`scripts/build_reviewer_comment_catalog.py`](scripts/build_reviewer_comment_catalog.py); Colab: [`notebooks/colab_build_comment_catalog.ipynb`](notebooks/colab_build_comment_catalog.ipynb).
- **Tests**: `tests/test_comment_catalog.py`.

## 0.8.7

- **HTML / Notion**: upload `.html`/`.htm`; `HTMLParser` (BeautifulSoup + lxml) with Notion detection (`.notion-body` or `meta generator`); artifacts `html_heading`, `html_paragraph`, `html_intro_paragraph`, `html_code_block`, `html_table`, `html_image`, `html_document`; default map `html_practicum_v1`.
- **Criteria categories**: `category` on every criterion in all maps; `CriterionResultDTO.category` and `metadata_json.category`; `GET /api/v1/config/criteria_categories`; `GET .../findings?category=`.
- **Rules**: optional `min_normalized_length` for rule checks (used by `html_min_text_length`).

## 0.8.6

- **Security**: allowlist for `criteria_map_code` / `style_profile_code`; DataLens capture URL allowlist (`https` + `*.datalens.yandex*` / `*.datalens.yandexcloud*`, toggle `DATALENS_URL_ALLOWLIST_ENABLED`); upload size cap `MAX_UPLOAD_BYTES`; `ProjectFileDTO` no longer exposes `storage_path`.
- **Reliability**: `run_review` sets `status=failed` and stores `metadata_json.error` on pipeline exceptions (`ReviewPipelineError` → HTTP 500); `zip(criteria, raw_results, strict=True)`.
- **Ops**: config paths anchored to package root; `DateTime(timezone=True)` + `datetime.now(UTC)` on `Project`; multi-stage `Dockerfile` (`production` / `development` targets); compose builds `development` target by default.
- **Quality**: dev deps `ruff` + `mypy`; GitHub Actions `ci.yml`; negative API tests (`test_validation.py`).

## 0.8.5

- **Retrieval**: `ReviewExample.source_kind` (`general` \| `project_training` \| `reviewer_reference`); опциональные `filter_source_project` и `filter_section_name` в `retrieve()`; фильтр проекта из `metadata_json.review_training_project` (upload) или `PROJECT_REVIEW_TRAINING_FILTER_PROJECT`; приоритет строк project-training с совпадающей `section_name`, затем с пустой секцией.
- **API**: форма `review_training_project` на `POST /api/v1/projects/upload` — slug для привязки к `source_project` в JSONL корпуса.
- **LLM**: в payload примеров передаётся `source_kind`; промпт `generate_comment` обновлён; тест `test_llm_generate_comment_prompt.py`.

## 0.8.4

- **Notebook roles**: маркеры `Комментарий мидл-ревьюера` / `Комментарий мидл ревьюера` + `infer_notebook_comment_role()`; `clean_notebook` удаляет ячейки ревьюера и мидл-ревьюера; в `metadata` добавлены `comment_role`, `is_middle_reviewer_comment`.
- **Project training corpus**: `ENABLE_PROJECT_REVIEW_TRAINING` + `PROJECT_REVIEW_TRAINING_PATH` (один `.jsonl` или каталог из нескольких JSONL); строки с `author_role: student` не попадают в retrieval для генерации комментариев; до двух примеров на запрос с разнообразием по `source_notebook`; пустой `criterion_code` в строке = wildcard для любого критерия.
- **ReviewExample**: поля `author_role`, `source_project`, `source_notebook`, `student_context`, `section_name`; промпт `generate_comment` учитывает роли и контекст без ground truth.
- **Tooling**: `scripts/build_review_training_corpus.py` и `app/retrieval/notebook_training.py` — сборка runtime + optional fine-tune JSONL из нескольких master-review `.ipynb`.
- **Colab**: `notebooks/colab_project_training_batch.ipynb` — пакетная выгрузка из папки с ноутбуками.

## 0.8.3

- **Retrieval**: optional `REVIEWER_REFERENCE_EXAMPLES_PATH` + `ENABLE_REVIEWER_REFERENCE_EXAMPLES` — JSONL из эталонного Colab старшего ревьюера; при совпадении с основным `REVIEW_EXAMPLES_PATH` в выдачу попадает до одного такого якоря на вызов (без фильтра по подстроке запроса). Промпт `generate_comment` получает `retrieval_examples` и явно запрещает трактовать эталон как рубрику или ground truth.
- **LLM**: исправлена передача `retrieval_examples` в шаблон комментария (раньше поле игнорировалось).
- **Colab**: `notebooks/colab_reviewer_reference_examples.ipynb` — загрузка эталонного `.ipynb` и генерация JSONL.

## 0.8.2

- **API**: `GET /api/v1/changelog` returns structured entries parsed from `CHANGELOG.md` (`package_version`, `entries[].version`, `entries[].items`); optional query `limit` (1–200).

## 0.8.1

- **DataLens capture scenario**: ordered steps (`navigate` → `wait_shell` → text extract → full-page shot → tab strip discovery → per-tab clicks with settle + `networkidle` wait); screenshots named `datalens_capture_full.png` plus `step_NN_tab_*.png`; `capture_step_log` with per-step timings and selector used; selector chains in `datalens_selectors.py` (tabs, shell-ready, nav fallbacks).
- **Capture pool**: bounded `ThreadPoolExecutor` (`CAPTURE_POOL_WORKERS`, `CAPTURE_POOL_TIMEOUT_SEC`, `CAPTURE_USE_POOL`); process metrics via `GET /api/v1/debug/capture_metrics`; INFO logging for `app.capture.*`.
- **Reporting**: `source_stage` is now **`llm`** when `llm_used` (notebook/sql semantic LLM paths); hybrid heuristics without LLM remain `semantic`.

## 0.8.0

- **LLM layer**: `app/llm/` with OpenAI-compatible `LLMClient`, `LLMService`, prompt templates under `app/llm/prompts/`, env-driven enable flags and graceful fallback when the API key is missing or LLM is disabled.
- **Semantic analysis**: notebook section-aware checks (`notebook_semantic`), SQL AST-backed checks (`sql_ast`, `sql_semantic`), dashboard text heuristics in `semantic.py`; findings carry `source_stage` and optional `llm_semantic` metadata.
- **Notebook**: `section_builder` assigns flow sections and enriches cell metadata; comment insertions are deduplicated.
- **SQL**: parser embeds `ast_report`; review markdown for SQL includes structured “Решение” / “Версия после правки” blocks without inventing full rewrites.
- **DataLens capture**: Playwright flow waits for `networkidle`, full-page shot, optional tab clicks, capture summary fields (`loaded_ok`, `discovered_tabs`, `extracted_text_length`, `capture_errors`); honest `skipped`/`disabled` when capture is off.
- **Visual pipeline**: richer region metadata (`region_id`, `region_confidence`, typed overlay colors, legend); extended `visual_summary` and `visual_preview` API; additional visual criteria in PDF/DataLens maps.
- **Explorer / debug**: artifact filters (`section_name`, `source_type`), findings filters (`severity`, `criterion_code`, `source_stage`), `GET .../debug/capture_summary`, `parser_summary`, `criteria_summary`.
- **Retrieval (optional)**: `app/retrieval/` local JSONL stub for future comment enhancement when `ENABLE_RETRIEVAL` and `REVIEW_EXAMPLES_PATH` are set.
- **Criteria**: `notebook_practicum_v2.json`, `sql_practicum_v2.json`; extended `dashboard_practicum_v1.json` and `datalens_practicum_v1.json`.
- **Tests**: coverage for LLM fallback, capture skip, SQL AST, notebook sections, visual summary/preview, API filters.

## 0.5.0 (baseline)

- Image-based regions, overlays, explorer endpoints, PDF/DataLens pipelines as shipped previously.
