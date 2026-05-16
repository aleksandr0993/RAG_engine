# Architecture Overview

Документ основан на структуре файлов и конфигурациях репозитория (commit `c2d90a4`, 2026-04-11).

## Таблица: слой / компонент

| Слой / компонент | Технология | Где находится | Назначение | Статус | Комментарий |
|------------------|------------|---------------|------------|--------|-------------|
| Frontend framework | Next.js 14, React 18 | `review_assistant_repo/frontend/` | SPA: загрузка, проекты, каталог, админ | Partially done | Минимальный набор страниц; зависимости без lockfile в git |
| Backend framework | FastAPI | `review_assistant_repo/app/` | REST API ревью и вспомогательные сервисы | Done (код) | Версия API 0.9.10 |
| Database | SQLite (default) / PostgreSQL | `app/db.py`, `DATABASE_URL` | Персистентность проектов | Production-like | Compose-файл для Postgres опционален |
| ORM | SQLAlchemy 2 | `app/models.py` | Модели и связи | Done | |
| Migrations | Alembic | `review_assistant_repo/alembic/` | Схема БД | Done | Fallback `create_all` в `main.py` |
| Auth | Supabase JWT (PyJWT) | `app/auth/deps.py`, `app/auth/supabase_jwt.py` | Опциональная защита write/debug/RL | Partially done | По умолчанию выключено — см. SECURITY |
| State management | React local / fetch | `frontend/lib/api.ts` | HTTP к API | Minimal | Нет Redux/Zustand в зависимостях |
| Validation | Pydantic v2 | `app/schemas.py`, роутеры | Запросы/ответы | Done | |
| UI library | Нативный CSS / минимум | `frontend/app/globals.css` | Базовые стили | Minimal | Нет MUI/Chakra в `package.json` |
| Background jobs | FastAPI BackgroundTasks + DB job rows | `review_service`, `review_tasks`, `rl/train_jobs` | Async review / RL train | Mostly done | Не найдено: отдельный Celery/RQ |
| Cache | не выделен | — | — | Missing | Не найдено Redis/memcached в зависимостях |
| File storage | Локальный диск + optional Supabase | `FILES_ROOT`, `app/storage/supabase_storage.py` | Загрузки и экспорт | Done / Optional | |
| Notifications | не найдено | — | Push/SMS/email | Missing | |
| Analytics | debug metrics endpoints, Prometheus text | `app/metrics.py`, `routers/health.py` | Наблюдаемость | Partially done | Не полноценный продуктовый analytics SDK |
| Tests | pytest | `review_assistant_repo/tests/`, `homework_reviewer_llm/tests/` | Регрессия | Done | Условные skip |
| CI/CD | GitHub Actions | `review_assistant_repo/.github/workflows/ci.yml` | ruff, mypy, pytest, README check | **Broken at repo root** | В корне `RAG_engine` нет `.github/` — см. комментарий |
| Docker | Dockerfile + compose | `review_assistant_repo/` | Локальный/прод образ API | Done | |
| Deployment platform | не указан | — | Хостинг | Unknown | Не найдено в репозитории |
| Logging | stdlib logging, JSON helper | `app/utils/logging_json.py` | Структурированные события | Done | |
| Monitoring | Prometheus endpoint | `/api/v1/metrics` | Метрики | Partially done | |
| Error tracking | не найдено | — | Sentry и т.п. | Missing | |
| ML / data processing | transformers/PEFT pipeline | `homework_reviewer_llm/training/` | QLoRA | Optional / train extra | Linux+GPU ожидается |
| Browser automation | Playwright | `app/capture/`, optional extra `[browser]` | DataLens capture | Optional | По умолчанию `ENABLE_BROWSER_CAPTURE=false` |
| External APIs | HTTP (httpx), OpenAI-compatible | `app/llm/client.py` | LLM / embeddings | Optional | |
| Migrations | Alembic | `alembic/versions/` | DB | Done | |
| Seed data | examples в репо | `review_assistant_repo/examples/` | Демо-файлы | Partial | Для homework `data/*` в .gitignore |
| Config management | pydantic-settings, `.env` | `app/config.py`, `.env.example` | Конфигурация | Done | |
| Feature flags | env booleans | `ENABLE_*` в `.env.example` | Включение подсистем | Done | |
| Cron jobs | не найдено | — | — | Missing | |
| Scripts | Python CLI | `review_assistant_repo/scripts/`, `homework_reviewer_llm/scripts/` | сборка корпусов, worker RL | Done | |
| CLI | uvicorn, scripts | Makefile, `pyproject` scripts | Запуск | Done | |
| Admin panel | Next.js routes | `frontend/app/admin/` | Assignments | Partially done | |
| Participant/user app | Student assistant HTML/API | `app/static/student_assistant.html`, `routers/student_assistant.py` | Помощь студенту | Partially done | Не полноценное отдельное мобильное приложение |
| Shared packages | нет workspace | — | Общий код между пакетами | Missing | Два изолированных пакета |
| Internal SDK | не найдено | — | — | Missing | |
| Generated types | не найдено | — | OpenAPI → TS | Missing | |
| API schemas | OpenAPI (FastAPI) | `/docs` | Контракт | Done | Проверка README: `check_readme_endpoints.py` |

**Комментарий по CI:** GitHub ищет workflow в `.github/workflows/` **в корне репозитория**. Текущий путь `review_assistant_repo/.github/workflows/ci.yml` **не стандартен** для репозитория `RAG_engine` — **низкая уверенность**, что workflow выполняется, пока не настроен `paths` в другом репо или submodule (в репозитории submodules **не найдено**).

## Таблица: библиотеки / сервисы

| Библиотека / сервис | Где используется | Для чего нужна | Критичность для MVP | Можно ли заменить |
|---------------------|------------------|----------------|----------------------|-------------------|
| FastAPI / Uvicorn | review backend | HTTP API | Critical | Да (другой web framework) |
| SQLAlchemy / Alembic | review backend | DB | Critical | Да |
| nbformat / nbclient | parsers, execution | Ноутбуки | Critical (для .ipynb) | Частично |
| sqlglot | analyzers | SQL AST | Important для SQL-трека | Да |
| PyMuPDF | parsers/pdf | PDF | Important для PDF-трека | Да |
| Playwright | capture (extra) | DataLens | Optional | Да / отключить |
| OpenAI-compatible API | llm | Семантика/комментарии | Optional (README: never required) | Да |
| Gymnasium / SB3 | rl (extras) | Эксперименты RL | Post-MVP | Да / отключить |
| Next.js / React | frontend | UI | Important для демо UI | Да |
| @supabase/supabase-js | frontend | Клиент auth | Optional | Да |
| sentence-transformers / sklearn | optional `[analysis]` | Каталог комментариев, retrieval | Optional | Да |
| torch / transformers / PEFT | homework `[train]` | Обучение | Post-MVP для LLM-пакета | Да |

---

## Вывод | Доказательство | Уровень уверенности

| Вывод | Доказательство | Уровень |
|--------|----------------|---------|
| Архитектура — fullstack + optional ML repo | `review_assistant_repo/app/main.py`, `frontend/`, `homework_reviewer_llm/` | High |
| Монорепозиторий без tooling workspace | Два `pyproject.toml`, один `.git` | High |
| CI в текущем виде, вероятно, не активен на GitHub для этого корня | `.github` только под `review_assistant_repo/`; `Glob` корня | Medium |
| RAG — часть review app, не отдельный сервис | `app/retrieval/`, README флаги | High |
