# Review Assistant for Practicum Projects

Hybrid review assistant for student analytics homework: **rules first**, optional **LLM semantic hints**, **SQL AST** checks, **PDF/DataLens** parsing with image regions and overlays, and **explorer/debug** HTTP APIs.

**Current package / API version: 0.9.10** (see `CHANGELOG.md` and `GET /api/v1/changelog`).

## Supported inputs

- `.ipynb`
- `.sql`
- `.pdf` dashboards
- `.html` / `.htm` (including Notion HTML export)
- DataLens URLs

### Яндекс Практикум: Jupyter и Ревизор

Работы приходят из разных мест учебного процесса:

- **Локальный Jupyter** или ноутбук, сданный как файл — обычно `.ipynb`; по умолчанию в метаданных проекта выставляется канал `jupyter`.
- **Платформа «Ревизор»** (код-ревью Практикума): часто тот же `.ipynb` или другой файл, **скачанный** с платформы. Укажите при загрузке форму `practicum_input_channel=revisor`, чтобы явно пометить источник (полезно для аналитики и дальнейших интеграций).
- Сохранённая **HTML**-страница: парсер вычисляет `practicum_revisor_detection_confidence` (`strong` \| `medium` \| `weak` \| `none`) и `practicum_revisor_detection_reasons`. Поднятие канала с `html` на `revisor` после ревью выполняется только при **medium** или **strong** (URL Практикума в разметке или в атрибутах `href`/`src`/…). Слабый сигнал только по кириллице «ревизор»+«практикум» без URL **не** меняет канал и не ставит `practicum_revisor_html_detected`.

Параметр загрузки: `practicum_input_channel` — пусто / `auto` (по умолчанию), `jupyter` (только для `.ipynb`), `revisor` (любой поддерживаемый тип файла).

## Outputs

- Findings per criterion (`pass` / `warn` / `fail` / `unknown`) with evidence and `metadata_json` (includes `source_stage`: `rule` | `semantic` | `visual` | **`llm`** when the criterion used the LLM; heuristic-only hybrid checks stay `semantic`)
- Final verdict: `pass` or `revise`
- `review_markdown` (SQL layout includes ✅ / ❌ / 🔧 / 🟢 / 📌 sections)
- `reviewed.ipynb` with reviewer comments (deduplicated templates)
- Visual artifacts: PDF page PNGs, overlays, DataLens captures
- Project `metadata_json`: parser/capture/criteria execution summaries, `review_pipeline_timeline`, `quality_summary` (`manual_review_needed`, reasons) for debugging

#### `metadata_json`: Практикум и Revisor (HTML)

| Ключ | Назначение |
|------|------------|
| `practicum_input_channel` | `jupyter` \| `revisor` \| `html` \| `sql` \| `pdf` \| `datalens` и др. — откуда/как классифицирована работа |
| `practicum_input_explicit` | `true`, если задано полем формы `practicum_input_channel`, иначе выведено из типа файла |
| `practicum_revisor_html_detected` | `true`, только при уверенности **medium** или **strong** (см. ниже) |
| `practicum_revisor_detection_confidence` | `none` \| `weak` \| `medium` \| `strong` |
| `practicum_revisor_detection_reasons` | список кодов правил, например `yandex_practicum_url_in_dom_attribute` |
| `practicum_revisor_score` | внутренний вес эвристики (0–4), для отладки |
| `iteration_fix_summary` | итерации: `status` (`evaluated`, `no_parent_link`, `no_parent_review_snapshot`, `nothing_to_verify`, `corrupt_metadata_normalized`, …), `counts`, `items`, `iteration_fix_policy_version`, связь с родительским проектом |
| `notebook_execution` | для `.ipynb`: результат `nbclient` (`notebook_execution_ok`, `skipped`, ошибки, длительность) или флаги «не применимо» / «отключено» |

## Implemented vs scaffold

| Area | Status |
|------|--------|
| Rule engine + JSON criteria maps | Production-like |
| SQL `sqlglot` AST checks | Production-like (heuristic) |
| Notebook section tagging + semantic heuristics | Stronger heuristics; LLM optional |
| LLM (`ENABLE_LLM*`) | Optional; **never required** for a full review |
| PDF text + image region heuristics | Production-like heuristics, not full CV |
| DataLens Playwright capture | **Off by default**; multi-screenshot/tab probe when enabled |
| RAG / retrieval | Local JSONL + эталон Colab + корпус мастер-ревью (`ENABLE_PROJECT_REVIEW_TRAINING`); **справочник типичных комментариев** (кластеризация по секции и цвету алерта) — скрипт `build_reviewer_comment_catalog.py`; не рубрика и не ground truth |

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
cp .env.example .env
uvicorn app.main:app --reload
```

Swagger: `http://127.0.0.1:8000/docs`

### Smoke test (upload → review → review_result)

Сервер должен быть уже запущен (`uvicorn ...`). Из каталога `review_assistant_repo`:

```bash
bash scripts/smoke_notebook_review.sh
# или
REVIEW_API_BASE=http://127.0.0.1:8000 bash scripts/smoke_notebook_review.sh
```

Скрипт использует `examples/sample_notebook.ipynb` и завершится с ошибкой, если в ответе `review_result` нет `final_verdict`.

### Reset local SQLite database (dev)

Если используется SQLite по умолчанию (`DATABASE_URL=sqlite:///./data/review_assistant.db` в `.env.example`):

1. Остановите процесс `uvicorn`.
2. Удалите файл базы по пути из `DATABASE_URL` (часто `./data/review_assistant.db` относительно текущей рабочей директории при запуске).
3. Запустите API снова — при `USE_ALEMBIC_MIGRATIONS=true` выполнится `alembic upgrade head` (или fallback `create_all`).

### Public staging / security (minimum)

Для **любого окружения**, где API доступен не только доверенным разработчикам в локальной сети:

| Переменная | Рекомендация |
|------------|----------------|
| `REQUIRE_AUTH_FOR_WRITES` | `true` — загрузка и мутации только с валидным Supabase JWT |
| `REQUIRE_AUTH_FOR_DEBUG_ROUTES` | `true` — закрыть `GET/POST /api/v1/debug/*` и `.../projects/{id}/debug/*` |
| `SUPABASE_JWT_SECRET` или `SUPABASE_JWKS_URL` | Нужны для проверки JWT (см. `app/auth/supabase_jwt.py`) |
| `REQUIRE_AUTH_FOR_RL_WRITES` | `true`, если включён `ENABLE_RL_ENGINE` и RL endpoints доступны извне |

Подробности по debug по умолчанию — в секции **API (explorer & debug)** ниже.

### Semantic / visual analyzers: `unknown` и `metadata.note`

Для части **hybrid / semantic / visual** задач в `app/analyzers/semantic.py` и `app/analyzers/visual.py` если задача (`task`) **не распознана** реализованными ветками, результат — `status: "unknown"`, низкая `confidence`, `metadata.source_stage` = `semantic` или `visual`, и `metadata.note` = `"not implemented"`. Это **не сбой HTTP**: критерий помечается как неподтверждённый автоматикой; при `severity: required` срабатывает политика качества (`FINDING_*` в `.env.example`). См. также колонку `source_stage` у findings в разделе **Outputs** выше.

### Optional CORS (SPA на другом origin)

В `.env`: **`CORS_ALLOWED_ORIGINS`** — список origin через запятую (например `http://localhost:3000,https://app.example.com`). Пусто — middleware не подключается. Для подходящего `Origin` браузер увидит **`Access-Control-Expose-Headers`** с `X-Total-Count`, `X-Total-Count-Truncated`, `X-Next-Cursor` (пагинация `GET /api/v1/projects`). **`CORS_ALLOW_CREDENTIALS`** — по умолчанию `false` (при `true` нельзя использовать `*` в origins).

### Docker

```bash
cp .env.example .env
docker compose up --build
```

Local compose uses the `development` image target (uvicorn `--reload`). For production builds use `docker build --target production -t review-api:prod .` and run without bind-mounting the source over `/app`.

### Optional PostgreSQL

```bash
docker compose -f docker-compose.yml -f docker-compose.postgres.yml up --build
```

### Optional browser capture (DataLens)

```bash
pip install -e .[browser]
playwright install chromium
```

Set `ENABLE_BROWSER_CAPTURE=true` in `.env`. Tune `CAPTURE_POOL_*`, `DATALENS_*` for pool size, timeouts, and per-step settle delays after navigation / tab clicks. Capture writes `capture_step_log` (per-step `duration_ms`, `selector_used`, `screenshot_path`) into project metadata and logs under the `app.capture` logger.

### Optional LLM

Set in `.env` (see `.env.example`):

- `ENABLE_LLM=true`
- `LLM_API_KEY=...`
- `LLM_MODEL=gpt-4o-mini` (or compatible model)
- Optionally `LLM_BASE_URL` for OpenAI-compatible proxies
- `ENABLE_LLM_SEMANTIC_CHECKS=true` / `ENABLE_LLM_COMMENT_GENERATION=true` as needed

If LLM is off or the key is missing, reviews complete using rules + heuristics only.

### Experimental RL engine addon

This project now includes an experimental RL engine extension with pluggable integrations:

- **Policy providers**: `random`, `openai` (OpenAI-compatible chat completions), `sb3` (Stable-Baselines3 checkpoint under `RL_MODELS_ROOT`)
- **Environment providers**: `toy_bandit` (local), `open_source_http` (adapter for external RL APIs), `gymnasium_discrete` (Gymnasium envs with discrete actions, e.g. `CartPole-v1`)

Optional open-source stack:

- **Gymnasium only** (discrete envs for rollouts): `pip install -e ".[rl]"` — small install.
- **+ Stable-Baselines3** (training + `policy=sb3`, pulls PyTorch): `pip install -e ".[rl,rl_sb3]"` — large download.

Enable in `.env`:

- `ENABLE_RL_ENGINE=true`
- Optional dedicated OpenAI settings for RL:
  - `RL_OPENAI_API_KEY=...` (falls back to `LLM_API_KEY`)
  - `RL_OPENAI_MODEL=gpt-4o-mini`
  - Optional `RL_OPENAI_BASE_URL` for OpenAI-compatible gateways
- `RL_MODELS_ROOT=./data/rl_models` — where `POST /rl/train` writes `*.zip` and `policy=sb3` loads checkpoints
- `RL_TRAIN_MAX_TIMESTEPS` — server-side cap for `total_timesteps` on `POST /rl/train` (default `500000`)
- `RL_TRAIN_MAX_CONCURRENT` — max simultaneous jobs in `accepted` / `running` (default `2`); extra requests get **429**
- `REQUIRE_AUTH_FOR_RL_WRITES=true` — require Supabase JWT (same style as `Authorization: Bearer` / `X-User-Token`) for `POST /rl/train*`, `GET /rl/train/jobs/{id}`; jobs store `created_by_sub` and poll is **403** for other users when ownership is set

Training jobs and artefact locks are stored in the **app database** (`rl_train_jobs`, `rl_train_artefact_locks`); run `alembic upgrade head` after deploy.

**External train worker (recommended for prod):** set `RL_TRAIN_ASYNC_EXECUTOR=external_worker`. Then `POST /rl/train/async` only enqueues (`accepted`); a separate process runs `python scripts/run_rl_train_worker.py` (or `make run-rl-worker`) with the **same** `DATABASE_URL`, `RL_MODELS_ROOT`, and `pip install -e ".[rl,rl_sb3]"`. Poll interval: `RL_TRAIN_WORKER_POLL_SEC`. Compose: `docker compose --profile rl-worker up`. `GET /api/v1/rl/health` exposes `rl_train_async_executor`.

Endpoints:

- `GET /api/v1/rl/health` — includes `gymnasium_available` / `stable_baselines3_available` when extras are installed
- `POST /api/v1/rl/episodes/run`
- `POST /api/v1/rl/train` — synchronous PPO / A2C / DQN (requires `rl_sb3`; blocks until done; use for short runs)
- `POST /api/v1/rl/train/async` — **202**; training in `BackgroundTasks`; poll `GET /api/v1/rl/train/jobs/{job_id}` (status persisted in DB)
- `GET /api/v1/rl/train/jobs/{job_id}` — `accepted` → `running` → `completed` | `failed`

### Optional retrieval / master-review training (several `.ipynb`)

1. **Маркеры в ячейках** (текст в source): `Комментарий ревьюера`, `Комментарий мидл-ревьюера` (или `Комментарий мидл ревьюера`), `Комментарий студента`.
2. Соберите JSONL из папки с ноутбуками:

```bash
python scripts/build_review_training_corpus.py \
  --input-dir ./data/master_reviews \
  --project my_project_slug \
  --runtime-out ./data/project_training.jsonl \
  --finetune-out ./data/finetune_dialogue.jsonl
```

3. В `.env`: `ENABLE_RETRIEVAL=true`, `ENABLE_LLM_COMMENT_GENERATION=true`, `ENABLE_PROJECT_REVIEW_TRAINING=true`, `PROJECT_REVIEW_TRAINING_PATH=./data/project_training.jsonl` (или каталог с несколькими `.jsonl`). В runtime-корпус попадают только `reviewer` и `middle_reviewer`; `finetune-out` содержит также `student` для внешнего fine-tuning.
4. **Фильтр проекта**: при загрузке ноутбука передайте форму `review_training_project` (тот же slug, что в `--project` при сборке JSONL), либо задайте глобально `PROJECT_REVIEW_TRAINING_FILTER_PROJECT`. Строки с пустым `source_project` в JSONL считаются wildcard.
5. **Секция**: для `.ipynb` примеры из корпуса сортируются по совпадению `section_name` с секцией якорной ячейки критерия.

См. `notebooks/colab_project_training_batch.ipynb` для Colab.

### Reviewer insertion memory from reviewed notebooks

Если есть архив или папка ноутбуков, где код студента не менялся, а в `.ipynb` добавлены только комментарии ревьюера, можно восстановить “чистый” исходник и дообучить память мест вставки комментариев:

```bash
python ../scripts/build_reviewer_insertion_memory_from_archive.py \
  --input /path/to/reviewed_notebooks_or_archive \
  --project games_preprocessing \
  --work-dir ./data/reviewer_memory_build/games_preprocessing \
  --output ./data/reviewer_insertions/games_preprocessing.jsonl \
  --report-md ./data/reviewer_memory_build/games_preprocessing/report.md \
  --report-json ./data/reviewer_memory_build/games_preprocessing/report.json
```

Скрипт поддерживает `.ipynb`, директории, `.zip`, `.tar`, `.tar.gz`, `.tgz`; пишет `manifest.jsonl`, `problem_files.txt`, восстановленные исходники в `restored_sources/`, а в отчётах подсвечивает неоднозначные случаи: отсутствие ревью-комментариев, нераспознанный цвет, слабые якоря и высокий процент комментариев без `criterion_code`.

### Project-specific briefs: Practicum Wiki HTML → course KB

Если у вас есть сохранённая HTML-страница с описанием проекта Практикума, её можно превратить в чистый текст для `STUDENT_COURSE_KB_DIR`:

```bash
python scripts/wiki_html_to_course_kb.py \
  /path/to/wiki-python-basics.html \
  --output ./data/course_kb/wiki-python-basics.md \
  --metadata-json ./data/course_kb/wiki-python-basics.meta.json
```

Для быстрого старта нового типа проекта используйте semi-automatic importer. Он создаёт course KB, metadata и **черновик** criteria map, который нужно отревьюить перед использованием в потоке ревью:

```bash
python scripts/import_project_brief.py \
  /path/to/wiki-python-basics.html \
  --slug games_preprocessing \
  --kind ipynb
```

Результаты:

- `./data/course_kb/games_preprocessing.md`
- `./data/course_kb/games_preprocessing.meta.json`
- `./configs/criteria_maps/ipynb_games_preprocessing_v1.json`

Если файл уже существует, importer завершится ошибкой; для пересоздания добавьте `--overwrite`.

Если есть авторское решение / ноутбук старшего ревьюера с цветными блоками `Критерии проверки` и `Комментарий автора`, импортируйте его отдельно:

```bash
python scripts/import_senior_review_notebook.py \
  /path/to/game_po_milestones.ipynb \
  --project games_preprocessing
```

Результаты:

- `./data/senior_review_guidance/games_preprocessing.json` — структурированная рубрика и цветовая политика
- `./data/senior_review_guidance/games_preprocessing.md` — удобный Markdown-конспект для ревью человеком
- `./data/project_training/games_preprocessing_senior_review.jsonl` — runtime-примеры для project-training retrieval

Чтобы эти формулировки использовались при генерации комментариев:

```env
ENABLE_RETRIEVAL=true
ENABLE_PROJECT_REVIEW_TRAINING=true
PROJECT_REVIEW_TRAINING_PATH=./data/project_training/games_preprocessing_senior_review.jsonl
```

При загрузке работы можно передать `review_training_project=games_preprocessing`, чтобы retrieval фильтровался по этому проекту.

Для проекта спринта 7 «Предобработка данных» добавлен отдельный критерий-карта:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/projects/upload \
  -F "file=@student_project.ipynb" \
  -F "criteria_map_code=notebook_games_preprocessing_v1"
```

Карта проверяет проектные сигналы по датасету `new_games.csv`: первичное знакомство, `snake_case`, типы оценок, пропуски, дубликаты, фильтр 2000–2013, категории оценок, top-7 платформ и выводы.

### Экспорт «живого» ревью для студенческого ноутбука

Для ручной проверки результата используйте скрипт экспорта. Он запускает Review Assistant в изолированной временной базе и сохраняет три артефакта:

- `*_live_reviewer_review.md` — текст ревью в формате, близком к сообщению живого ревьюера
- `*_reviewed_by_assistant.ipynb` — ноутбук с вставленными комментариями ревьюера
- `*_review_result.json` — технический JSON с критериями, статусами и evidence

```bash
python scripts/export_live_reviewer_artifacts.py \
  /path/to/student_project.ipynb \
  --criteria-map-code notebook_games_preprocessing_v1 \
  --review-training-project games_preprocessing \
  --output-dir ./data/student_samples
```

Для присланного пилотного ноутбука ориентиры такие:

- `./data/student_samples/pilot_live_reviewer_review.md`
- `./data/student_samples/homework_1778527421_reviewed_by_assistant.ipynb`
- `./data/student_samples/pilot_review_result_after_cleanup.json`

Перед боевой проверкой реального студента сначала смотрите `*_reviewed_by_assistant.ipynb`: это самый близкий к платформенному сценарию вид результата. Markdown удобен как короткое итоговое ревью, JSON нужен для аудита причин срабатывания критериев.

### Память мест вставки комментариев ревьюера

Чтобы учиться не только формулировкам, но и местам вставки комментариев, соберите JSONL из пары `исходник студента → проверенный ревьюером ноутбук`:

```bash
python scripts/extract_reviewer_insertions.py \
  ./data/student_samples/comparison_18680554/student_homework_1746533884.ipynb \
  ./data/student_samples/comparison_18680554/human_review_1746614288.ipynb \
  --project games_preprocessing \
  --output ./data/reviewer_insertions/games_preprocessing.jsonl
```

JSONL хранит устойчивые якоря: цвет комментария, предполагаемый критерий, ближайший раздел, признаки соседней студенческой ячейки (`fillna`, `rating`, `groupby`, `platform` и т.п.) и локальный контекст. В автопроверке эта память влияет только на место вставки комментария, а не на статус критерия.

Включение:

```env
ENABLE_REVIEWER_INSERTION_MEMORY=true
REVIEWER_INSERTIONS_PATH=./data/reviewer_insertions/games_preprocessing.jsonl
REVIEWER_INSERTION_MIN_SCORE=0.45
```

### Справочник типичных комментариев ревьюера (много `.ipynb`)

Офлайн-инструмент: кластеризация по **секции** (`section_name`) и **цвету** алерта в HTML (`alert-danger` / `alert-warning` / `alert-success`). Результат — JSON и опционально Markdown; **не** считается рубрикой и не задаёт эталонных оценок.

```bash
python scripts/build_reviewer_comment_catalog.py \
  --input-dir ./data/reviewed_notebooks \
  --project my_corpus \
  --output ./data/reviewer_comment_catalog.json \
  --output-md ./data/reviewer_comment_catalog.md \
  --method heuristic \
  --sim-threshold 0.55
```

Для семантической кластеризации: `pip install -e .[analysis]`, затем `--method tfidf_kmeans` (опционально `--n-clusters`). Флаг `--include-student` добавляет в JSON блок `student_context_samples` без включения в кластеры.

См. `notebooks/colab_build_comment_catalog.ipynb`.

## API (core)

- `GET /api/v1/health`
- `GET /api/v1/changelog` — JSON changelog from `CHANGELOG.md` (optional `limit`)
- `GET /api/v1/projects` — list projects; query: `limit`, `offset`, `cursor` (keyset: не сочетать с `offset≠0`), `practicum_input_channel`, `source_type`, `status`, `include_total` (по умолчанию `true`; `false` — без COUNT и без `X-Total-Count*`); сортировка `created_at` desc, `id` desc; заголовки `X-Total-Count`, при необходимости `X-Total-Count-Truncated`, при наличии следующей страницы `X-Next-Cursor` (передать как `cursor` в следующем запросе). Keyset с `practicum_input_channel` — только SQLite/PostgreSQL; иначе `422` и используйте `offset`
- `POST /api/v1/projects/upload`
- `POST /api/v1/projects/{project_id}/review`
- `POST /api/v1/projects/{project_id}/review/async` — **202**; durable `ReviewJob` row; poll job status below
- `GET /api/v1/projects/{project_id}/review/jobs/{job_id}` — `queued` \| `running` \| `done` \| `failed`
- `GET /api/v1/projects/{project_id}`
- `GET /api/v1/projects/{project_id}/findings` — query: `severity`, `criterion_code`, `source_stage` (`rule` \| `semantic` \| `visual` \| `llm`), `category` (matches criterion map `category`, e.g. `structure`, `technical`)
- `GET /api/v1/projects/{project_id}/review_result`
- `GET /api/v1/projects/{project_id}/files`
- `GET /api/v1/projects/{project_id}/files/{file_id}`
- `GET /api/v1/projects/{project_id}/export/reviewed_notebook`
- `GET /api/v1/config/criteria`
- `GET /api/v1/config/criteria_categories` — map of category → criterion codes (aggregated across all criteria maps)
- `GET /api/v1/config/style_profiles`
- `GET /api/v1/rl/health`
- `POST /api/v1/rl/episodes/run` — run one experimental episode (`toy_bandit`, `open_source_http`, or `gymnasium_discrete`; policy `random`, `openai`, or `sb3`)
- `POST /api/v1/rl/train` — train SB3 agent (sync; requires `pip install -e ".[rl,rl_sb3]"`)
- `POST /api/v1/rl/train/async` — queue SB3 training (202 + job id)
- `GET /api/v1/rl/train/jobs/{job_id}` — training job status

## API (explorer & debug)

По умолчанию debug-эндпоинты **без** JWT. Для продакшена задайте в `.env`: `REQUIRE_AUTH_FOR_DEBUG_ROUTES=true` и один из `SUPABASE_JWT_SECRET` / `SUPABASE_JWKS_URL` — тогда ко всем путям ниже нужен тот же стиль токена, что и для `REQUIRE_AUTH_FOR_WRITES` / `REQUIRE_AUTH_FOR_RL_WRITES` (`Authorization: Bearer <jwt>` или заголовок `X-User-Token`).

- `GET /api/v1/projects/{project_id}/artifacts` — filters: `artifact_type`, `region_kind`, `page_no`, `tag`, `section_name`, `source_type` (`image`|`text` in metadata)
- `GET /api/v1/projects/{project_id}/artifacts/{artifact_id}`
- `GET /api/v1/projects/{project_id}/regions` — filters: `region_kind`, `page_no`, `source_type`
- `GET /api/v1/projects/{project_id}/visual_summary` — includes region counts, low-text / low-confidence page hints
- `GET /api/v1/projects/{project_id}/visual_preview` — `page_no`: base file, overlay, regions, summary
- `GET /api/v1/projects/{project_id}/debug/capture_summary`
- `GET /api/v1/projects/{project_id}/debug/parser_summary`
- `GET /api/v1/projects/{project_id}/debug/criteria_summary`
- `GET /api/v1/projects/{project_id}/debug/review_timeline` — pipeline stage durations + criteria / quality breakdown
- `GET /api/v1/debug/capture_metrics` — global capture pool counters (submitted / ok / fail / timeouts, durations)
- `GET /api/v1/debug/review_metrics` — review latency counters, low-confidence rollup, p50/p95 ms
- `GET /api/v1/debug/practicum_stats` — rollup по последним проектам: канал Практикума, `practicum_revisor_detection_confidence`, `source_type`, `project` `status`, `final_verdict`, число `practicum_revisor_html_detected`; query: `limit`, опционально `source_type`, `status`, `practicum_input_channel` (как у списка проектов; в ответе блок `filters`)
- `GET /api/v1/debug/metadata_quality_audit` — выборка последних проектов, счётчики проблем в `metadata_json.iteration_fix_summary` (query `sample_limit`)
- `POST /api/v1/debug/metadata_backfill` — нормализация `iteration_fix_summary` / `notebook_execution` и строк `iteration_issue_resolutions.detail_json` (query `project_limit`, `resolution_limit`; коммит в БД)

## Criteria maps

Default maps (upload): `notebook_practicum_v1`, `sql_practicum_v1`, `dashboard_practicum_v1`, `datalens_practicum_v1`.

Extended maps (opt-in via `criteria_map_code` on upload):

- `notebook_practicum_v2` — section-aware semantic criteria
- `sql_practicum_v2` — AST division / JOIN / GROUP BY checks (may duplicate legacy division rule by design for teaching clarity)

## Repository map

```text
app/
  analyzers/     # rules, semantic, visual, sql_ast, sql_semantic, notebook_semantic, visual_summary
  capture/       # datalens, scenario, selectors, pool, metrics
  exporters/
  llm/           # client, service, types, prompts/*.txt
  rl/            # experimental RL engine (Gymnasium / SB3 / OpenAI policy)
  parsers/
  retrieval/     # JSONL retrieval, notebook_training, comment_catalog (offline)
  routers/
  services/      # review, explorer, summaries, section_builder, comment_dedup, …
  utils/
configs/
  criteria_maps/
  style_profiles/
examples/
tests/
```

## Upload examples

Notebook: `curl -X POST http://127.0.0.1:8000/api/v1/projects/upload -F "file=@examples/sample_notebook.ipynb"`

SQL: `curl -X POST http://127.0.0.1:8000/api/v1/projects/upload -F "file=@examples/sample_query.sql"`

PDF: `curl -X POST http://127.0.0.1:8000/api/v1/projects/upload -F "file=@examples/sample_dashboard.pdf"`

DataLens: `curl -X POST http://127.0.0.1:8000/api/v1/projects/upload -F "source_url=https://datalens.yandex/..."`

Явно пометить работу из **Ревизора** (любой поддерживаемый файл):

`curl -X POST http://127.0.0.1:8000/api/v1/projects/upload -F "file=@examples/sample_query.sql" -F "practicum_input_channel=revisor"`

HTML с **URL Практикума** в разметке (после `POST .../review` при medium/strong канал может стать `revisor`, см. таблицу метаданных выше): загрузите свой `report.html` с ссылкой вида `https://practicum.yandex.ru/...`.

Список проектов только с каналом `revisor`:

`curl "http://127.0.0.1:8000/api/v1/projects?practicum_input_channel=revisor&limit=50"`

Только SQL-проекты в статусе `done`:

`curl "http://127.0.0.1:8000/api/v1/projects?source_type=sql&status=done&limit=100"`

Пагинация списка (`offset` — смещение после сортировки по дате создания):

`curl "http://127.0.0.1:8000/api/v1/projects?limit=20&offset=40"`

Следующая страница по курсору (значение `X-Next-Cursor` из предыдущего ответа):

`curl "http://127.0.0.1:8000/api/v1/projects?limit=20&cursor=PASTE_CURSOR_HERE"`

Без подсчёта общего числа строк (быстрее при длинной ленте):

`curl "http://127.0.0.1:8000/api/v1/projects?limit=50&include_total=false"`

Сводка по каналам (отладка):

`curl "http://127.0.0.1:8000/api/v1/debug/practicum_stats?limit=500"`

Та же сводка только по SQL-проектам в статусе `done`:

`curl "http://127.0.0.1:8000/api/v1/debug/practicum_stats?limit=200&source_type=sql&status=done"`

Сводка по последним проектам с каналом `revisor` в метаданных:

`curl "http://127.0.0.1:8000/api/v1/debug/practicum_stats?limit=300&practicum_input_channel=revisor"`

## Tests

```bash
pytest tests/
```

Playwright-dependent failure-path test is skipped if `playwright` is not installed.

## Honest limitations (next iterations)

- Stronger chart/table CV, async job queue, production auth, richer RAG over real review corpora, deeper DataLens DOM stability across UI changes.
