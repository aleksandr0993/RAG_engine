# Полное bug-focused код-ревью репозитория RAG_engine

**Дата:** 2026-04-11  
**Охват:** весь репозиторий — [`review_assistant_repo`](review_assistant_repo/), [`homework_reviewer_llm`](homework_reviewer_llm/). Исключены `.venv` и runtime-артефакты.  
**Приоритет:** баги и логические ошибки (корректность, безопасность, гонки).

---

## Краткое резюме

| Проект | Критичность | Главные темы |
|--------|-------------|--------------|
| `review_assistant_repo` | Высокая | path traversal при загрузке, SSRF в RL episode, RCE при выполнении notebook, гонки async review, опасный fallback миграций |
| `homework_reviewer_llm` | Средняя–высокая | dedupe по префиксу текста (потеря данных), хрупкий `evaluate.py`, нет bound на `overall_score`, дубликаты в v2 guardrails |

Ниже — единый формат: **severity → файл → сценарий → impact → fix**.

---

## Critical

### C1. Path traversal при записи загруженного файла

| Поле | Значение |
|------|----------|
| **Файл** | [`review_assistant_repo/app/services/review_service.py`](review_assistant_repo/app/services/review_service.py) — `ReviewService.upload_project` |
| **Сценарий** | `original_filename` вида `../../outside/evil.ipynb` (или смешанные разделители). Строка `destination = project_dir / (original_filename or ...)` не нормализует имя к basename. |
| **Impact** | Запись произвольных файлов на ФС процесса (перезапись, размещение payload). |
| **Fix** | `safe_name = Path(original_filename or "unnamed").name`; опционально whitelist символов; `destination.resolve().is_relative_to(Path(settings.files_root).resolve())` перед `shutil.copy`. |

### C2. SSRF и отсутствие аутентификации на запуск RL-эпизода

| Поле | Значение |
|------|----------|
| **Файлы** | [`review_assistant_repo/app/routers/rl.py`](review_assistant_repo/app/routers/rl.py) — `run_rl_episode` (без `Depends` на auth); [`review_assistant_repo/app/rl/environments.py`](review_assistant_repo/app/rl/environments.py) — `OpenSourceHttpEnvironment` (`httpx` к `base_url` + пути). |
| **Сценарий** | При `ENABLE_RL_ENGINE=true` клиент задаёт `environment=open_source_http` и `base_url` на metadata/cloud или внутренние сервисы. |
| **Impact** | SSRF, релей трафика, расход квот при policy с внешними вызовами. |
| **Fix** | Требовать auth (как для train) или отдельный ключ; allowlist хостов/схем; по умолчанию отключать вне dev; лимиты timeout и размера ответа. |

### C3. Выполнение кода из notebook на хосте (RCE при включённом флаге)

| Поле | Значение |
|------|----------|
| **Файлы** | [`review_assistant_repo/app/services/notebook_execution.py`](review_assistant_repo/app/services/notebook_execution.py) — `execute_notebook_to_file` (`NotebookClient`); вызов из [`review_assistant_repo/app/services/review_service.py`](review_assistant_repo/app/services/review_service.py) при `enable_notebook_execution`. |
| **Сценарий** | Пользователь загружает `.ipynb` с вредоносными ячейками; код выполняется с правами воркера API. |
| **Impact** | Полный RCE на multi-tenant без изоляции. |
| **Fix** | Песочница (контейнер/отдельный воркер без сети), жёсткий default `false` в prod, лимиты ресурсов; документировать риск. |

---

## High

### H1. Fallback `create_all` после ошибки Alembic

| Поле | Значение |
|------|----------|
| **Файл** | [`review_assistant_repo/app/main.py`](review_assistant_repo/app/main.py) — `_apply_schema` |
| **Сценарий** | `alembic upgrade` падает (права, битая миграция); логируется warning и вызывается `create_all`. |
| **Impact** | Расхождение схемы с production, скрытые поломки данных. |
| **Fix** | В non-dev — fail fast; `create_all` только под явным флагом / `app_env=dev`. |

### H2. TOCTOU: дублирующиеся async review jobs

| Поле | Значение |
|------|----------|
| **Файлы** | [`review_assistant_repo/app/routers/projects.py`](review_assistant_repo/app/routers/projects.py) — `run_review_async`; [`review_assistant_repo/app/models.py`](review_assistant_repo/app/models.py) — `ReviewJob` без unique partial index на активные job на `project_id`. |
| **Сценарий** | Два параллельных `POST .../review/async` оба видят отсутствие active job и ставят `processing` + два `ReviewJob`. |
| **Impact** | Двойная нагрузка, гонки состояния проекта. |
| **Fix** | Транзакция + `SELECT ... FOR UPDATE` по `Project`, или unique partial index `(project_id) WHERE status IN ('queued','running')`, или advisory lock. |

### H3. Скачивание файла без проверки пути относительно `files_root`

| Поле | Значение |
|------|----------|
| **Файл** | [`review_assistant_repo/app/routers/projects.py`](review_assistant_repo/app/routers/projects.py) — `download_project_file`, `download_reviewed_notebook` |
| **Сценарий** | `ProjectFile.storage_path` указывает вне корня (после C1, ручная правка БД, будущий баг). |
| **Impact** | Чтение произвольных файлов, доступных процессу. |
| **Fix** | `resolved = path.resolve();` требовать `resolved.is_relative_to(Path(settings.files_root).resolve())`. |

### H4. Утечка временных файлов при ошибках upload

| Поле | Значение |
|------|----------|
| **Файл** | [`review_assistant_repo/app/routers/projects.py`](review_assistant_repo/app/routers/projects.py) — `upload_project` |
| **Сценарий** | `NamedTemporaryFile(delete=False)`; `unlink` только при `ValueError` из `upload_project` и в конце успеха. Исключение из `ReviewService` (не `ValueError`) или из commit — tmp остаётся. |
| **Impact** | Засорение диска. |
| **Fix** | `try` / `finally` с `unlink(missing_ok=True)` для `tmp_file_path`. |

### H5. Dedupe по первым 2000 символам submission — потеря различимых записей

| Поле | Значение |
|------|----------|
| **Файл** | [`homework_reviewer_llm/src/homework_reviewer_llm/sanitize.py`](homework_reviewer_llm/src/homework_reviewer_llm/sanitize.py) — `dedupe_by_submission_hash` |
| **Сценарий** | Два разных сабмишена одного студента по одному заданию с общим префиксом >2000 символов дают один хеш — второй отбрасывается. |
| **Impact** | Тихая потеря примеров для train/eval, смещение метрик. |
| **Fix** | Хешировать полный `submission_text` (streaming SHA-256) или включать стабильный `id` из источника. |

### H6. `evaluate.py`: KeyError и молчаливые дубликаты `id`

| Поле | Значение |
|------|----------|
| **Файл** | [`homework_reviewer_llm/scripts/evaluate.py`](homework_reviewer_llm/scripts/evaluate.py) |
| **Сценарий** | Строка pred без `"id"`/`"raw"` → `KeyError`; дубликаты `id` в gold/pred — «последняя строка побеждает». |
| **Impact** | Падение отчёта; неверные MAE/метрики без сигнала. |
| **Fix** | `.get()` + счётчик пропусков; детект дубликатов при загрузке (warn/fail). |

### H7. Base-model inference / OOM и device (CUDA vs MPS)

| Поле | Значение |
|------|----------|
| **Файлы** | [`homework_reviewer_llm/scripts/inference_mvp.py`](homework_reviewer_llm/scripts/inference_mvp.py), [`homework_reviewer_llm/scripts/batch_inference.py`](homework_reviewer_llm/scripts/batch_inference.py) |
| **Сценарий** | Большая модель без адаптера в fp32; тензоры только под CUDA при модели на MPS. |
| **Impact** | OOM или runtime errors на Apple Silicon. |
| **Fix** | Явный dtype/quantization; унифицировать `device` с `model.device` и MPS. |

---

## Medium

### M1. Детали исключений JWT в HTTP-ответе

| **Файл** | [`review_assistant_repo/app/auth/deps.py`](review_assistant_repo/app/auth/deps.py) |
| **Сценарий** | `detail=f"Invalid token: {exc}"` может раскрывать внутренности. |
| **Fix** | Логировать на сервере; клиенту — фиксированное сообщение. |

### M2. `get_current_user_optional`: широкий `except Exception`

| **Файл** | [`review_assistant_repo/app/auth/deps.py`](review_assistant_repo/app/auth/deps.py) |
| **Сценарий** | Любая ошибка декодирования маскируется как «нет пользователя». |
| **Fix** | Ловить только `jwt.PyJWTError` (и сетевые ошибки JWKS отдельно с логированием). |

### M3. RL train: лимит конкурентности не атомарен

| **Файл** | [`review_assistant_repo/app/rl/train_jobs.py`](review_assistant_repo/app/rl/train_jobs.py) — `register_train_job_db` |
| **Сценарий** | Два запроса одновременно проходят проверку `count < max`. |
| **Fix** | Serializable isolation, advisory lock, или один атомарный SQL. |

### M4. WebSocket статуса проекта без auth

| **Файл** | [`review_assistant_repo/app/routers/projects.py`](review_assistant_repo/app/routers/projects.py) — `project_status_websocket` |
| **Сценарий** | Зная UUID, клиент видит `status` (в т.ч. `null` для несуществующего id). |
| **Fix** | Тот же уровень auth, что у read API, или подписанный токен в query. |

### M5. Чтение статуса RL train job при выключенной проверке владельца

| **Файл** | [`review_assistant_repo/app/routers/rl.py`](review_assistant_repo/app/routers/rl.py) — `rl_train_job_status` |
| **Сценарий** | `require_auth_for_rl_writes=false` — любой с `job_id` читает метаданные. |
| **Fix** | В prod требовать auth для чтения или непредсказуемые токены. |

### M6. `run_review_background`: любой `ValueError` → `project_not_found`

| **Файл** | [`review_assistant_repo/app/services/review_tasks.py`](review_assistant_repo/app/services/review_tasks.py) |
| **Сценарий** | Новый код в `run_review` кидает `ValueError` по другой причине. |
| **Fix** | Свой тип исключения для «проект не найден» или узкий match. |

### M7. Таймаут пула capture не отменяет работу воркера

| **Файл** | [`review_assistant_repo/app/capture/pool.py`](review_assistant_repo/app/capture/pool.py) — `run_capture_task` |
| **Сценарий** | После `fut.cancel()` поток Playwright может продолжать работу. |
| **Impact** | Накопление ресурсов под нагрузкой; семантика таймаута вводит в заблуждение. |
| **Fix** | Документировать; по возможности subprocess с kill; или уменьшать параллелизм. |

### M8. `shutdown(wait=False)` у executor захвата

| **Файл** | [`review_assistant_repo/app/capture/pool.py`](review_assistant_repo/app/capture/pool.py) |
| **Сценарий** | При resize/atexit задачи обрываются без ожидания. |
| **Fix** | `wait=True` при корректном shutdown; таймаут + лог. |

### M9. Кэш `get_llm_service` и смена конфигурации

| **Файл** | [`review_assistant_repo/app/llm/service.py`](review_assistant_repo/app/llm/service.py) |
| **Сценарий** | `@lru_cache(maxsize=1)` — смена env/settings не обновляет клиент до рестарта. |
| **Fix** | Ключ кэша от fingerprint настроек или без кэша / явный reset. |

### M10. Guardrails v2: дубликаты `factor_id` в списке

| **Файл** | [`homework_reviewer_llm/src/homework_reviewer_llm/guardrails.py`](homework_reviewer_llm/src/homework_reviewer_llm/guardrails.py) — `validate_review_output_v2` |
| **Сценарий** | Набор `factor_id` покрывает три фактора, но в списке дубликаты — проверка множеством проходит. |
| **Fix** | Проверка `len(factor_analysis) == len(FACTOR_IDS)` и уникальность id. |

### M11. `merge_jsonl` в pipeline — память

| **Файл** | [`homework_reviewer_llm/scripts/pipeline_local.py`](homework_reviewer_llm/scripts/pipeline_local.py) |
| **Сценарий** | Очень большие JSONL читаются целиком. |
| **Fix** | Потоковое слияние по строкам. |

---

## Low

### L1. Пустой/некорректный ответ chat API трактуется как пустая строка

| **Файл** | [`review_assistant_repo/app/llm/client.py`](review_assistant_repo/app/llm/client.py) |
| **Fix** | Явно различать пустой content и ошибку схемы; логировать raw. |

### L2. Embeddings: предположение о форме ответа OpenAI

| **Файл** | [`review_assistant_repo/app/retrieval/embed_backend.py`](review_assistant_repo/app/retrieval/embed_backend.py) |
| **Fix** | Валидация длины/ключей; fail fast с понятной ошибкой. |

### L3. Greedy JSON extraction в LLM

| **Файл** | [`review_assistant_repo/app/llm/client.py`](review_assistant_repo/app/llm/client.py) — `_extract_json_object` |
| **Fix** | Balanced-brace парсер или structured output API. |

### L4. Supabase upload: ошибка только в metadata

| **Файл** | [`review_assistant_repo/app/services/review_service.py`](review_assistant_repo/app/services/review_service.py) |
| **Fix** | Режим «strict»: если storage обязателен — fail upload. |

### L5. `overall_score` без границ 0–100 в Pydantic

| **Файл** | [`homework_reviewer_llm/src/homework_reviewer_llm/schema.py`](homework_reviewer_llm/src/homework_reviewer_llm/schema.py) — `ReviewOutput`, `ReviewOutputV2` |
| **Fix** | `Field(ge=0, le=100)` где это семантика процентов. |

### L6. `strip_json_fence` и несколько fenced блоков

| **Файл** | [`homework_reviewer_llm/src/homework_reviewer_llm/schema.py`](homework_reviewer_llm/src/homework_reviewer_llm/schema.py) |
| **Fix** | Извлекать первый завершённый fence или первый JSON-объект. |

### L7. Пустой датасет в `train_qlora.py`

| **Файл** | [`homework_reviewer_llm/training/train_qlora.py`](homework_reviewer_llm/training/train_qlora.py) |
| **Fix** | Ранняя проверка `len(rows)==0` с понятным exit. |

### L8. Блокирующий `upload_project` в async-роуте

| **Файл** | [`review_assistant_repo/app/routers/projects.py`](review_assistant_repo/app/routers/projects.py) |
| **Fix** | `asyncio.to_thread` для тяжёлого sync-кода или sync endpoint + worker. |

---

## Оптимизации и надёжность (привязка к файлам)

1. **[`app/llm/client.py`](review_assistant_repo/app/llm/client.py)** — переиспользовать `httpx.Client` с пулом соединений вместо нового клиента на каждый вызов.
2. **[`app/storage/supabase_storage.py`](review_assistant_repo/app/storage/supabase_storage.py)** — то же для upload; таймауты из settings.
3. **[`app/routers/projects.py`](review_assistant_repo/app/routers/projects.py)** — WebSocket: длинноживущая сессия БД или реже открывать/закрывать pool.
4. **[`app/rl/train_jobs.py`](review_assistant_repo/app/rl/train_jobs.py)** — claim job одним `UPDATE ... RETURNING` / `SKIP LOCKED` где поддерживается PostgreSQL.
5. **[`app/routers/projects.py`](review_assistant_repo/app/routers/projects.py)** — фильтры findings в SQL, а не загрузка всех `CriterionResult` в Python.
6. **[`app/db.py`](review_assistant_repo/app/db.py)** — для PostgreSQL: `pool_pre_ping`, настройка размера пула из env.
7. **[`app/main.py`](review_assistant_repo/app/main.py)** — миграции в init-job/контейнере, не в каждом воркере uvicorn.
8. **[`app/services/review_service.py`](review_assistant_repo/app/services/review_service.py)** — bulk insert для больших объёмов `Artifact` при необходимости.
9. **[`app/config.py`](review_assistant_repo/app/config.py)** — опасные default (notebook execution, auth off) только в dev или за явным флагом.
10. **[`homework_reviewer_llm/scripts/batch_inference.py`](homework_reviewer_llm/scripts/batch_inference.py)** — `torch.inference_mode()`, батчинг, явный device.
11. **[`homework_reviewer_llm/scripts/pipeline_local.py`](homework_reviewer_llm/scripts/pipeline_local.py)** — streaming `merge_jsonl` (см. M11).
12. **Semantic/hybrid retrieval** — [`app/retrieval/hybrid_backend.py`](review_assistant_repo/app/retrieval/hybrid_backend.py), [`embed_backend.py`](review_assistant_repo/app/retrieval/embed_backend.py): тесты под `ENABLE_SEMANTIC_RETRIEVAL=true` и моки HTTP.

---

## Регрессионные и edge-case тесты (минимальный набор)

| Риск | Идея теста |
|------|------------|
| C1 path traversal | Upload с `filename="../../../tmp/x.ipynb"` → 400 или путь строго под `project_id/`. |
| C2 SSRF | С моком httpx: запрос к запрещённому host → 403; allowlist пропускает только dev URL. |
| H2 async review race | Два параллельных `TestClient` POST async → один 202, второй 409 (после фикса — стабильно). |
| H3 download path | Запись в БД `storage_path` вне root → 404 или 403. |
| H4 temp leak | Искусственный raise после записи tmp → файл удалён в `finally`. |
| H5 dedupe | Два `NormalizedRecord` с разным хвостом после 2000 символов → оба в выходе после фикса. |
| H6 evaluate | pred без `id` → не падает, счётчик `skipped_lines`; дубликаты id → warning/error. |
| M1 JWT detail | Невалидный токен → ответ без внутреннего текста исключения. |
| Alembic fail | В тесте подменить `command.upgrade` на raise → в prod-режиме процесс не стартует (после H1). |
| Embeddings malformed | Мок ответа без `embedding` → понятная ошибка, не KeyError в глубине. |

---

## Roadmap внедрения

### P0 — безопасность и целостность данных
- C1, C2, C3 (или жёсткое отключение notebook execution + SSRF/auth в RL).
- H1 (Alembic), H3 (path check на download).
- H4 (finally для tmp).

### P1 — корректность и гонки
- H2 (async review), M3 (RL concurrent cap).
- H5, H6, H7 (`homework_reviewer_llm`).
- M6, M9, M10, Pydantic bounds (L5).

### P2 — надёжность под нагрузкой и DX
- M7, M8 (capture pool), L8 (async upload).
- Оптимизации HTTP-клиентов, SQL-фильтры, миграции в init.
- Расширение CI: semantic retrieval path, JWKS (RS256), circuit breaker LLM.

---

## Заключение

Критический риск сосредоточен в **`review_assistant_repo`** (загрузка файлов, RL HTTP, notebook execution, схема БД при старте). В **`homework_reviewer_llm`** главные логические риски — **dedupe**, **evaluate.py** и **валидация score/guardrails**. Документ можно использовать как backlog: каждый ID (C/H/M/L) — отдельная задача с тестом из таблицы выше.
