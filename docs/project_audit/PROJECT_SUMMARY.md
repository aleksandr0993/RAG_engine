# Project Summary

## 1. Краткое описание проекта

Корневой репозиторий `RAG_engine` — **монорепозиторий** из двух Python-пакетов без README в корне:

| Пакет | Назначение |
|--------|------------|
| `review_assistant_repo` | FastAPI-приложение «Review Assistant for Practicum Projects»: гибридное автоматическое ревью домашних работ (ноутбуки, SQL, PDF, HTML, DataLens), опциональный LLM, RAG/retrieval, экспериментальный RL-движок, Next.js SPA, Alembic, Docker. Версия пакета **0.9.10** (`review_assistant_repo/pyproject.toml`, `CHANGELOG.md`). |
| `homework_reviewer_llm` | Пайплайн данных и эксперимент **SFT/QLoRA** для дообучения LLM под формат ревью: санитизация, split, JSONL, обучение, метрики, MVP-инференс. Версия **0.1.0**. |

Имя корневой папки `RAG_engine` **шире**, чем фактическое содержимое: в репозитории нет отдельного «движка RAG» как единого продукта; RAG/retrieval — **подсистема** внутри `review_assistant_repo` (флаги `ENABLE_RETRIEVAL`, `ENABLE_PROJECT_REVIEW_TRAINING`, гибридный retrieval в `app/retrieval/`).

**Доказательства:** корень — только `.gitignore`, `CODE_REVIEW.md`, `CODE_REVIEW_BUG_FOCUSED.md`, два каталога пакетов; `git ls-files` не содержит `README.md` в корне (commit `c2d90a4`).

## 2. Бизнес-смысл

Автоматизация и стандартизация **ревью учебных работ** в стиле Яндекс Практикум: снижение нагрузки на ревьюеров, ускорение обратной связи, единые критерии (JSON criteria maps), воспроизводимый артефакт (`reviewed.ipynb`, markdown-ревью, findings). Параллельно — **исследовательский трек**: сбор корпуса и fine-tuning модели под тот же домен (`homework_reviewer_llm`).

**Интерпретация на основе README/CHANGELOG:** целевая аудитория — команда курса / платформа / внутренний инструмент Практикума; прямой B2C в репозитории не описан.

## 3. Основные пользовательские сценарии

1. Загрузка файла или URL → создание проекта → запуск ревью (синхронно или async job) → просмотр findings / экспорт ноутбука.
2. Опционально: включение LLM для семантики и генерации комментариев.
3. Опционально: retrieval из JSONL / master-review ноутбуков.
4. Админ: назначения (`assignments`), отладочные эндпоинты, метрики.
5. Эксперимент RL (отдельный модуль, не обязателен для основного ревью).
6. Отдельный сценарий `homework_reviewer_llm`: CSV/JSONL → pipeline → облачное обучение → evaluate/inference.

**Доказательства:** `review_assistant_repo/README.md`, `app/routers/projects.py`, `homework_reviewer_llm/README.md`.

## 4. Архитектура

- **Backend:** FastAPI, слоистая структура `parsers` → `analyzers` / `services` → `routers`; SQLAlchemy + SQLite по умолчанию или PostgreSQL через `DATABASE_URL`.
- **Frontend:** Next.js 14 в `review_assistant_repo/frontend/`, вызовы REST к `NEXT_PUBLIC_API_URL`.
- **Данные:** файлы на диске (`FILES_ROOT`, `EXPORTS_ROOT`), опционально Supabase Storage.
- **homework_reviewer_llm:** библиотека + CLI-скрипты, без веб-сервера в пакете.

## 5. Технологический стек

| Область | Технологии |
|---------|------------|
| API | FastAPI, Uvicorn, Pydantic v2 |
| DB | SQLAlchemy 2, Alembic |
| Парсинг | nbformat, nbclient, sqlglot, PyMuPDF, BeautifulSoup/lxml |
| LLM | OpenAI-совместимый клиент (опционально) |
| RL | Gymnasium, опционально Stable-Baselines3 |
| Frontend | Next.js 14, React 18, TypeScript, `@supabase/supabase-js` |
| ML пакет | pydantic; train extras: torch, transformers, peft, trl, … |
| Контейнеры | Docker, docker-compose |

## 6. Структура репозитория

```
RAG_engine/                 # нет корневого README
  CODE_REVIEW*.md
  homework_reviewer_llm/    # ML pipeline package
  review_assistant_repo/    # основное приложение + frontend + tests + CI (вложенный .github)
docs/
  project_audit/            # данный аудит
```

**Признак монорепозитория:** два независимых `pyproject.toml`, общий git, без workspace-менеджера (pnpm/npm workspaces **не найдено**).

## 7. Основные сервисы и модули

- `app.main:create_app` — точка входа ASGI, роутеры под `/api/v1`.
- `app.services.review_service` — оркестрация пайплайна ревью.
- `app.retrieval.*` — примеры, hybrid/BM25, project training JSONL.
- `app.rl.*` — экспериментальный RL API.
- `homework_reviewer_llm` — `schema`, `sanitize`, `split`, `sft_format`, скрипты `scripts/`.

## 8. База данных и модели данных

- Модели в `review_assistant_repo/app/models.py` (проекты, файлы, артефакты, findings, jobs, RL jobs и т.д.).
- Миграции Alembic: `review_assistant_repo/alembic/versions/*.py` (initial, rl tables, review_jobs, iteration snapshots).
- При старте: `USE_ALEMBIC_MIGRATIONS=true` → `alembic upgrade head`, при ошибке fallback `create_all` (`app/main.py`).

## 9. API / backend

REST под префиксом `/api/v1`: health, changelog, config, projects (upload, review, async jobs, export), debug, RL, student assistant, assignments. Полный перечень — в `review_assistant_repo/README.md`; сверка с OpenAPI — скрипт `scripts/check_readme_endpoints.py` (используется во **вложенном** CI).

## 10. Frontend / UI

`review_assistant_repo/frontend/`: страницы `login`, `dashboard`, `projects/upload`, `projects/[id]`, `catalog`, `admin/assignments`. API-хелпер: `frontend/lib/api.ts`.

## 11. Авторизация и безопасность

- Опциональный **Supabase JWT** для записей и debug/RL (настройки `SUPABASE_*`, `REQUIRE_AUTH_FOR_*` в `.env.example`).
- По умолчанию debug-маршруты без JWT (см. README — риск для продакшена без конфигурации).

## 12. Интеграции

- OpenAI-совместимый LLM (опционально).
- Supabase (JWT, Storage) — опционально.
- DataLens URL + Playwright capture — опционально, по умолчанию выключено.
- Внешние модели эмбеддингов / FAISS — через optional extras `[analysis]`.

## 13. Тестирование

- `review_assistant_repo/tests/` — **47** файлов `test_*.py`.
- `homework_reviewer_llm/tests/` — **12** файлов.
- Часть тестов условно пропускается (`pytest.importorskip`, `skipif` при отсутствии sample/playwright/sklearn).

## 14. Локальный запуск

- **Review Assistant:** `cd review_assistant_repo`, venv, `pip install -e .[dev]`, `cp .env.example .env`, `uvicorn app.main:app --reload`. Frontend отдельно: `cd frontend && npm install && npm run dev` (**не найдено** lockfile для frontend в списке tracked файлов — см. LOCAL_SETUP_AUDIT).
- **homework_reviewer_llm:** `cd homework_reviewer_llm`, `pip install -e .` или `.[train]` для GPU-обучения.

## 15. Деплой

- Dockerfile multi-stage (`development` / `production`) в `review_assistant_repo/Dockerfile`.
- `docker-compose.yml` + опционально `docker-compose.postgres.yml`.
- **Не найдено в репозитории:** корневой Kubernetes/Helm, Terraform, явный PaaS-манифест для review app.

## 16. Что уже сделано

- Полнофункциональный каркас review API с обширными тестами и документацией внутри пакета.
- Критерии, парсеры, политика качества findings, async review jobs, экспорт ноутбука, метрики, RL addon, student assistant.
- ML-пакет: схемы, пайплайн скрипты, тесты на логику без обязательного GPU.

## 17. Что не завершено / требует внимания

- **Интеграция монорепозитория:** нет корневого README; GitHub Actions лежит только в `review_assistant_repo/.github/` — **стандартный CI GitHub в корне репозитория не найден** (см. RISK_REGISTER).
- README `homework_reviewer_llm` ссылается на пути под `data/` — каталог **не в git** из-за `.gitignore` (`**/data/`) — новый разработчик не получит шаблоны из клонирования без ручного создания или изменения gitignore.
- Отдельные ветки анализаторов возвращают `metadata.note: "not implemented"` (см. UNFINISHED_WORK).

## 18. Технический долг

- Дублирование «истории продукта» в CHANGELOG vs один коммит в git (процесс релизов не виден в git).
- RL и retrieval — большая поверхность при зависимости как «опционально».
- Frontend без lockfile в tracked files — риск дрейфа зависимостей.

## 19. Риски

Сводка в `RISK_REGISTER.md`: CI в корне, onboarding монорепо, опциональная auth по умолчанию, внешние LLM/DataLens.

## 20. План до MVP

См. `MVP_ROADMAP.md` и уточнение: **MVP для какого продукта** — основной review API (ближе к готовности) или объединённый «RAG_engine» как платформа (требует интеграционной работы в корне).

## 21. Оценка сроков

См. `PROJECT_AUDIT_REPORT.md` → раздел Time Estimate. **Уровень уверенности: Low–Medium** из-за одного git-коммита и отсутствия истории задач/issues.

## 22. Рекомендации по следующему этапу

1. Корневой README с картой монорепо и командами для обоих пакетов.
2. Перенос или дублирование `.github/workflows` в **корень** с `working-directory: review_assistant_repo` (или split репозиториев).
3. Явно задокументировать политику `data/` для `homework_reviewer_llm` (git LFS, отдельный архив, или исключение из gitignore для `data/templates` / `data/samples`).
