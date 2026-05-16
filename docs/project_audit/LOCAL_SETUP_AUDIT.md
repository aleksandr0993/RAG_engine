# Local Setup Audit

Проверки выполнены по файлам репозитория (без `npm install` / `pip install` в этой сессии — **read-only** диагностика).

| Проверка локального запуска | Статус | Где видно | Проблема | Как исправить |
|-----------------------------|--------|-----------|----------|---------------|
| Корневой README с инструкцией | Missing | `git ls-files` нет `README.md` в корне | Нет единой точки входа | Добавить README |
| README в `review_assistant_repo` | OK | `review_assistant_repo/README.md` | — | — |
| README в `homework_reviewer_llm` | Partial | `homework_reviewer_llm/README.md` ссылается на `data/templates`, `data/samples` | Пути не в git (`.gitignore` `**/data/`) | Политика артефактов / исключения |
| `.env.example` для API | OK | `review_assistant_repo/.env.example` | — | — |
| Описание env переменных | OK | Тот же файл, комментарии | — | — |
| docker-compose | OK | `review_assistant_repo/docker-compose.yml`, `docker-compose.postgres.yml` | Требуется `.env` рядом | `cp .env.example .env` в README |
| Dockerfile | OK | `review_assistant_repo/Dockerfile` | — | — |
| Миграции Alembic | OK | `review_assistant_repo/alembic/` | — | — |
| Seed данные | Partial | `review_assistant_repo/examples/*`; homework samples — см. выше | homework без данных в клоне | см. выше |
| Команды dev/build/test/lint (backend) | OK | `Makefile` (`install`, `run`, `test`), `pyproject.toml` scripts | — | — |
| package scripts frontend | OK | `frontend/package.json` (`dev`, `build`, `start`, `lint`) | — | — |
| Lockfile frontend | Missing | `git ls-files review_assistant_repo/frontend/*lock*` — пусто | Невоспроизводимые версии npm | Закоммитить lockfile |
| Версия Python указана | OK | `requires-python >=3.11` (review), `>=3.10` (homework) | Два разных минимума | Документировать в корневом README |
| `.nvmrc` / `.python-version` | Missing | Glob по корню — **не найдено** | Мягкий риск версий | Добавить при желании |
| Инструкция первого запуска | OK | `review_assistant_repo/README.md` Quick start | Для монорепо — нет | Корневой README |
| Сброс БД | Partial | SQLite путь в `.env.example`; явной команды «drop db» **не найдено** | Удалить файл БД вручную | Документировать |
| Запуск тестов | OK | `pytest tests/` в README | — | — |
| CI в корне | Broken / Missing | Нет `.github` в корне `RAG_engine` | Автоматическая проверка для mono | Перенос workflow |
| Скрытые внешние зависимости | Partial | LLM, Supabase, Playwright — опционально | Демо без ключей OK для rules-only | README уже описывает |

---

## Local Setup Verdict

**Can run with minor fixes** для `review_assistant_repo` при следовании его README (venv, pip install, .env).

**Can run only with project owner help** для полного монорепо-онбординга из-за отсутствия корневого README и homework `data/` вне git.

**Evidence:** `review_assistant_repo/README.md` строки Quick start; корневой `.gitignore` строка `**/data/`; отсутствие корневого README.

---

## Вывод | Доказательство | Уровень уверенности

| Вывод | Доказательство | Уровень |
|--------|----------------|---------|
| API пакет документирован для локального запуска | README Quick start + Makefile | High |
| Frontend reproducibility слабее без lockfile | `git ls-files` frontend locks | High |
| Полный «mono» onboarding не готов | Нет корневого README | High |
