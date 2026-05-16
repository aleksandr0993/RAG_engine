# Next 10 Tasks

Упорядочены для разблокировки онбординга, CI и демо. Все задачи **подтверждаются** текущим состоянием репозитория (commit `c2d90a4`).

| № | Задача | Где работать | Зачем | Зависимости | Acceptance Criteria | Оценка | MVP-critical |
|---|--------|--------------|-------|-------------|---------------------|--------|--------------|
| 1 | Добавить корневой `README.md` с описанием монорепо и ссылками на оба пакета | `/Users/mac/RAG_engine/README.md` (новый файл) | Онбординг без чтения git history | нет | Клон → чтение README → понятны `cd` и цели обоих каталогов | 0.5 д | Да |
| 2 | Настроить GitHub Actions в **корне** репозитория с `working-directory: review_assistant_repo` для шагов Python | `.github/workflows/ci.yml` (новый в корне) или перенос существующего | Автоматическая проверка PR | доступ к GitHub org | Push запускает ruff, mypy, pytest; зелёный лог | 0.5–1 д | Да |
| 3 | Закоммитить `package-lock.json` (или `pnpm-lock.yaml`) для `review_assistant_repo/frontend` | `review_assistant_repo/frontend/` | Воспроизводимая сборка UI | нет | `npm ci` успешен на чистой машине; lock в git | 0.25 д | Да (для UI-демо) |
| 4 | Разрешить противоречие `homework_reviewer_llm` README ↔ `.gitignore` для `data/` | корневой `.gitignore` и/или `homework_reviewer_llm/` | Тесты README не «ломаются» на клоне | согласование с владельцем | Либо `data/templates` в git, либо README с явным «создайте файлы вручную» + ссылка на gist/релиз | 1 д | Нет (для ML-трека) |
| 5 | Документировать «сброс БД» для SQLite dev | `review_assistant_repo/README.md` | Быстрый recovery | нет | Явные шаги: остановить uvicorn, удалить путь из `DATABASE_URL`, перезапуск | 0.25 д | Нет |
| 6 | Smoke-скрипт одной командой: upload sample notebook + review + GET result | `review_assistant_repo/scripts/` или расширить `demo_requests.sh` | Демо/регрессия | задача 1 опционально | Exit code 0; JSON содержит `final_verdict` или эквивалент в ответах API | 1 д | Да |
| 7 | Проверить и задокументировать минимальный набор env для публичного staging | `review_assistant_repo/README.md` + `.env.example` | Безопасный staging | SECURITY аудит | Таблица: prod must-have (`REQUIRE_AUTH_FOR_*`) | 0.5 д | Да для prod |
| 8 | Добавить `.python-version` или `requires` в корневой документ | корень или README | Снижение дрейфа Python | нет | Указаны 3.11 для review, 3.10+ для homework | 0.25 д | Нет |
| 9 | Расширить тест или документацию для веток `semantic`/`visual` с `note: not implemented` | `app/analyzers/semantic.py`, `visual.py`, тесты | Прозрачность для пользователя API | продуктовое решение | Либо код возвращает осмысленный статус, либо API-док описывает `unknown` | 2–3 д | Нет |
| 10 | Описать в корневом README отсутствие интеграции «RAG_engine» как единого сервиса | корневой README | Снятие путаницы с именем папки | задача 1 | Явная фраза: имя репо vs два продукта | 0.25 д | Нет |

---

## Suggested GitHub Issues

### Issue: Add root README for RAG_engine monorepo

**Description:**  
Репозиторий содержит `review_assistant_repo` и `homework_reviewer_llm`, но в корне нет README. Новые разработчики не видят точки входа.

**Acceptance Criteria:**
- В корне есть `README.md`.
- Перечислены оба подпроекта, версии (из pyproject), ссылки на их README.
- Команды «быстрый старт» для API и (опционально) frontend.

**Priority:** P0

**Estimate:** 0.5 d

---

### Issue: Enable CI at repository root

**Description:**  
Workflow находится в `review_assistant_repo/.github/workflows/ci.yml`. Для типичного GitHub remote на корне `RAG_engine` workflow не выполняется.

**Acceptance Criteria:**
- Workflow в `.github/workflows/` **корня** репозитория.
- Шаги используют `defaults.run.working-directory: review_assistant_repo` или эквивалент.
- `pytest`, `ruff`, `mypy` как минимум совпадают с текущим workflow.

**Priority:** P0

**Estimate:** 1 d

---

### Issue: Commit frontend lockfile

**Description:**  
В git не отслеживается lockfile для Next.js приложения.

**Acceptance Criteria:**
- `package-lock.json` или `pnpm-lock.yaml` в `review_assistant_repo/frontend/`.
- Документирована команда установки (`npm ci`).

**Priority:** P1

**Estimate:** 0.25 d

---

### Issue: Homework reviewer — data directory policy

**Description:**  
README ссылается на `data/templates/...`, но `**/data/` в корневом `.gitignore` исключает эти пути из коммитов.

**Acceptance Criteria:**
- Либо шаблоны попадают в git (узкое исключение в `.gitignore`), либо README обновлён с альтернативной инструкцией.
- `pytest` в `homework_reviewer_llm` проходит на чистом клоне без ручных файлов **или** явно документированы обязательные ручные шаги.

**Priority:** P1

**Estimate:** 1 d

---

### Issue: API smoke script for notebook review

**Description:**  
Автоматизировать проверку основного сценария upload+review для `examples/sample_notebook.ipynb`.

**Acceptance Criteria:**
- Скрипт в `review_assistant_repo/scripts/` с exit code 0 на успех.
- Использует только локальный API (127.0.0.1) и файлы из `examples/`.

**Priority:** P1

**Estimate:** 1 d
