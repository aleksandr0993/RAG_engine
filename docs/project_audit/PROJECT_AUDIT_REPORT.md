# Project Audit Report

**Репозиторий:** `RAG_engine` (локальный путь аудита: workspace).  
**Единственный коммит в Git:** `c2d90a4` от **2026-04-11** — сообщение: *«docs: add bug-focused CODE_REVIEW; init monorepo (homework_reviewer_llm, review_assistant_repo)»*.  
**Авторы Git (короткий log):** 1 (`Aleksandr`).  
**Issues в репозитории:** не найдены (нет `.github/ISSUE_TEMPLATE`, нет ссылок на трекер).

---

## Executive Summary

Гибридный **Review Assistant** для учебных работ Практикума (ноутбуки, SQL, PDF, HTML, DataLens) с опциональным LLM, retrieval и экспериментальным RL — **основная зрелая кодовая база** в `review_assistant_repo` (версия **0.9.10**, обширные тесты и README). Второй пакет — **`homework_reviewer_llm`**: пайплайн данных и QLoRA/SFT для отдельного ML-трека (v0.1.0). Имя корня **RAG_engine** шире фактического содержимого: отдельного RAG-сервиса нет; RAG — подсистема review-приложения.

**MVP:** для сценария «загрузка → ревью без LLM → результат/экспорт ноутбука» код и документация пакета review выглядят **близко к MVP**; **монорепозиторий как продукт** — **не** (нет корневого README, CI не в корне GitHub, homework `data/` не в git из-за `.gitignore`).

**Demo:** возможна **с подготовкой** (см. `DEMO_READINESS.md`).

**Локальный запуск:** API по README `review_assistant_repo` — **ожидаемо OK**; полный onboarding монорепо — **с мелкими правками/документацией**.

**Главные риски:** CI в нестандартном пути; debug API без JWT по умолчанию; отсутствие lockfile frontend; расхождение homework README и gitignore для `data/`.

**Рекомендация:** **Finish MVP first** + точечная стабилизация (корень README, CI, lockfile), без архитектурного redesign.

**Оценка времени до MVP (реалистично):** порядка **5–15 человеко-дней** (1–3 календарные недели при 1 FTE) на интеграцию монорепо, безопасность staging, smoke E2E; **низкая уверенность** из-за одного git-коммита и отсутствия backlog.

---

## Executive Summary for Investor / Partner

Продукт — **автоматизированное ревью учебных аналитических работ** с формализованными критериями и экспортом правок в Jupyter. Решает проблему **масштабирования ревью** и **единообразия фидбека** для онлайн-школы/курсов (ориентир Практикум — в README). Ценность — экономия времени ревьюеров и предсказуемый формат замечаний. **Кодовая база review-модуля объёмная и тестированная**, но **история разработки в этом Git не видна** (один импортный коммит). Риски: безопасность публичного API при дефолтных настройках, зависимость от внешних LLM как опции, зрелость UI как тонкого клиента. **Инвестиционная готовность** к data room / due diligence потребует вынести CI, секрет-менеджмент и product metrics **за пределы текущего минимума** — см. риски.

---

## Executive Summary for New Developer

Это **монорепозиторий из двух Python-пакетов**. Главный runtime — **`review_assistant_repo`**: FastAPI (`app.main:create_app`), SQLAlchemy, Alembic, pytest. Старт: README внутри этой папки, `pip install -e .[dev]`, `.env` из `.env.example`, `uvicorn app.main:app --reload`. Фронт — **`review_assistant_repo/frontend`** (Next 14). Второй пакет — **`homework_reviewer_llm`**: библиотека + скрипты для датасета и обучения; читать его README; учти, что **`data/` игнорируется git** в корне. **Начни с:** `review_assistant_repo/README.md` → `app/main.py` → `app/services/review_service.py` → `app/routers/projects.py`.

---

## Executive Summary for Project Owner

Уже сделано: **большой рабочий каркас Review Assistant** с API, критериями, парсерами, джобами ревью, тестами, Docker, CHANGELOG 0.8.x–0.9.10 (как документ эволюции продукта). Сейчас: **код импортирован в новый git-репозиторий одним коммитом** — нет видимой истории задач. Осталось для «продуктового» монорепо: **корневой README**, **CI в корне**, **lockfile фронта**, **политика данных homework**. Следующий шаг: задачи из `NEXT_10_TASKS.md` (первые три — максимальный эффект).

---

## Business Goals

| Бизнес-цель | Как реализуется | Статус | Где видно | Комментарий |
|-------------|-----------------|--------|-----------|-------------|
| Автоматическое ревью работ | Пайплайн parse → rules/semantic/visual → findings → markdown + notebook | Done (ядро) | `review_service.py`, README | LLM optional |
| Поддержка нескольких форматов сдачи | Парсеры ipynb/sql/pdf/html/datalens | Done | `app/parsers/` | DataLens capture optional |
| Снижение доли ручной рутины | Criteria maps, шаблоны комментариев, async jobs | Mostly done | `configs/`, jobs API | |
| Сбор корпуса для улучшения качества | JSONL training, comment catalog scripts | Partially done | `scripts/`, `retrieval/` | Данные вне репо |
| Дообучение LLM под стиль ревью | homework pipeline + QLoRA | Partially done | `homework_reviewer_llm/` | Отдельный трек |
| Эксперименты RL | RL API + worker | Post-MVP / R&D | `app/rl/` | README: experimental |

---

## Product Scope

- **In scope (код):** review API, критерии, хранение проектов, экспорт ноутбука, debug/metrics, optional LLM/RAG/RL, Next.js UI-скелет, ML preprocessing package.
- **Out of scope / не найдено:** биллинг, мультитенантность SaaS, нативные мобильные клиенты, централизованный issue tracker в репо.

---

## Development Timeline

### Таблица (Git + документированная эволюция версий)

| Период / дата | Что было сделано | Затронутые части | Доказательства | Комментарий |
|---------------|------------------|------------------|----------------|-------------|
| 2026-04-11 | Инициализация монорепозитория: добавлены `homework_reviewer_llm`, `review_assistant_repo`, `CODE_REVIEW*.md`, `.gitignore` | Весь репозиторий | commit `c2d90a4`; `git log` | Единственный коммит — **нет детальной git-хронологии** внутри этого репо |
| Н/Д → 0.9.10 (даты между версиями **не найдены** в репозитории) | Последовательные релизы review assistant (API, auth debug, CORS, jobs, retrieval, …) | `review_assistant_repo` | `CHANGELOG.md` (секции 0.8.x–0.9.10) | **Интерпретация:** история разработки **продукта** зафиксирована в CHANGELOG, но **не в git-графе** данного корня |
| Н/Д | ML пакет v0.1.0 как эксперимент SFT/QLoRA | `homework_reviewer_llm` | `homework_reviewer_llm/pyproject.toml`, README | Версия ниже review-app |

### Development Timeline Summary

- **Фактический старт Git-репозитория `RAG_engine`:** 2026-04-11 (один коммит).
- **Первый рабочий этап в этом репо:** импорт уже собранного дерева файлов.
- **Основная архитектура в git:** появилась **сразу** в составе импорта — этапы **не разложены** по коммитам.
- **Ключевые функции (по CHANGELOG/README):** эволюция описана текстом в `CHANGELOG.md` (например durable review jobs в 0.9.0, CORS в 0.9.10).
- **Пик разработки по Git:** **невозможно локализовать** — один коммит.
- **Незавершённое по следам кода:** semantic/visual ветки `not implemented`; optional подсистемы выключены по умолчанию.
- **Стабильность развития по Git:** **низкая наблюдаемость**; по CHANGELOG — инкрементальные версии **выглядят** стабильной эволюцией продукта (**Medium**, интерпретация).

### Метрики скорости (по Git и файлам)

| Метрика | Значение | Комментарий |
|---------|----------|-------------|
| Первый коммит | 2026-04-11 `c2d90a4` | Совпадает с последним |
| Последний коммит | 2026-04-11 `c2d90a4` | |
| Всего коммитов | 1 | Нет распределения по времени |
| Активных дней (Git) | 1 | |
| Среднее коммитов на активный день | 1 | Метрика неинформативна при N=1 |
| Изменённых файлов в коммите | 248 (`git show --stat`) | Большой единовременный импорт |
| Строк (+) в коммите | ~22 742 insertions (`git log --stat`) | Объём «снимка», не темп ongoing |
| Число авторов Git | 1 (`git shortlog -sn`) | |
| Самые часто изменяемые файлы по истории | **невозможно** ранжировать | Нужна многокоммитная история |
| Нестабильные зоны по частоте коммитов | **Unknown** | Одна ревизия |
| Крупные архитектурные смены в Git | **не видны** | См. `CHANGELOG.md` как текстовую эволюцию версий |
| Типы задач быстрее/медленнее | **невозможно подтвердить по Git** | |
| Периоды интенсивной разработки / паузы | **не найдены в Git** | |
| Откаты / большие рефакторинги в Git | **не найдены** | |
| Альтернативный источник «темпа» | `review_assistant_repo/CHANGELOG.md` (0.8.x–0.9.10) | Даты между версиями в файле **не указаны** — **низкая детализация** |

---

## Architecture Summary

См. `ARCHITECTURE_OVERVIEW.md`. Кратко: **fullstack** (FastAPI + Next.js) + **optional ML repo**; монорепозиторий **без** npm/pnpm workspace; **RAG** как часть `review_assistant_repo`.

---

## Tech Stack Summary

Python 3.11+ (review), 3.10+ (homework); FastAPI; SQLAlchemy; Alembic; Next.js 14; pytest; Docker; optional Playwright, OpenAI-compatible API, Gymnasium/SB3.

---

## Current MVP Readiness

### Таблица функций

| Функция | Статус | Готовность % | Где реализована | Что осталось | Критичность для MVP |
|---------|--------|--------------|-----------------|--------------|---------------------|
| Upload проектов | Done | 90–100% | `routers/projects.py` | — | MVP-critical |
| Sync review | Done | 90–100% | `review_service.py` | Стабилизация edge cases | MVP-critical |
| Async review jobs | Done | 85–95% | jobs tables, API | Наблюдаемость очереди prod | Important |
| Export reviewed.ipynb | Done | 85–95% | `exporters/notebook.py` | Валидация на широком корпусе | MVP-critical |
| Rule + SQL AST checks | Done | 85–95% | `analyzers/rules.py`, `sql_ast.py` | — | MVP-critical |
| Semantic / visual heuristics | Partially done | 60–80% | `semantic.py`, `visual.py` | Ветки `not implemented` | Important |
| LLM comments / semantic | Optional | 70% при включении | `llm/` | Ключи, cost | Nice-to-have |
| Retrieval / RAG | Partially done | 50–70% при данных | `retrieval/` | Корпус JSONL | Important / post-MVP |
| DataLens capture | Mostly done (off) | 50–70% | `capture/` | Playwright, флаги | Post-MVP |
| RL engine | Experimental | 40–60% | `rl/` | deps, worker | Post-MVP |
| Frontend UI | Partially done | 50–70% | `frontend/` | lockfile, polish | Important |
| homework LLM pipeline | Mostly done (offline) | 60–80% | scripts + train | Данные в git | Post-MVP для основного MVP review |

### MVP Readiness Summary

- **Близок ли MVP (review-only, rules path):** **да, в основном**.
- **Блокирует MVP:** публичный деплой без hardening auth (**конфиг**, не отсутствие кода); интеграция репозитория (CI/README).
- **Не блокирует:** RL; rich RAG; DataLens если выключены.
- **Демонстрировать уже можно:** API + `examples/sample_notebook.ipynb`.
- **Стабилизировать:** semantic/visual хвосты; UI reproducibility.
- **Post-MVP:** RL как продуктовая фича; MLflow; полноценный SaaS.

---

## Completed Work

- Полный каркас Review Assistant согласно README и тестам (**47** test files в review package).
- Alembic миграции, Docker, Makefile, OpenAPI, скрипты корпусов.
- homework_reviewer_llm: схемы, санитизация, split, SFT builders, train script, **12** test modules.

---

## Unfinished Work

Детализация: `UNFINISHED_WORK.md`.

---

## Definition of Done for MVP

| MVP-блок | Definition of Done | Как проверить | Критичность |
|----------|---------------------|---------------|-------------|
| Локальный запуск API | `uvicorn` стартует, `/docs` открывается | Ручной smoke | Critical |
| Env | Документирован минимальный `.env` для rules-only | Сверка с `.env.example` | Critical |
| БД | Миграции или create_all успешны на чистой БД | Удалить sqlite файл, перезапуск | Critical |
| E2E сценарий | upload sample ipynb → review → есть verdict | Скрипт или ручной curl | Critical |
| Ошибки | 4xx/5xx с телом ошибки на неверный input | Негативные тесты / ручной | Important |
| Тесты | `pytest` зелёный в CI | CI в корне | Important |
| Demo data | `examples/` для review | Файлы в git | Important |
| Секреты | Нет реальных ключей в git | grep / git history policy | Critical |
| Сценарий без ручного патча кода | Достижим через конфиг | Чеклист владельца | Critical |

### MVP Acceptance Scenario

1. Оператор поднимает API из `review_assistant_repo` с `.env` без LLM.
2. Выполняет upload `examples/sample_notebook.ipynb` с корректными полями criteria/style.
3. Запускает review и получает статус завершения.
4. Система сохраняет findings и итоговый verdict в БД и отдаёт их по API.
5. Оператор скачивает `reviewed.ipynb` и видит вставленные markdown-комментарии.
6. **Итог:** демо «ревью без человека» для стандартного примера проходит.

---

## Demo Readiness

См. `DEMO_READINESS.md`. Вердикт: **Demo possible with preparation**.

---

## Local Setup Audit

См. `LOCAL_SETUP_AUDIT.md`. Вердикт: **Can run with minor fixes** (review); **Can run only with project owner help** для полного mono без доработок.

---

## Security / Privacy Audit

См. `SECURITY_PRIVACY_AUDIT.md`. Ключевое: включить auth для debug/write на любой публичной среде.

---

## Technical Debt

- Git-история не отражает разработку; полагаться на CHANGELOG + дисциплину коммитов вперёд.
- Semantic/visual `not implemented` ветки.
- RL поверхность при «включили по ошибке».
- Frontend без lockfile.

---

## Risk Register Summary

См. `RISK_REGISTER.md`. Top: CI placement, debug auth defaults, mono onboarding, homework data path, frontend locks.

---

## Refactor vs Finish Recommendation

| Область проекта | Текущее состояние | Рекомендация | Почему | Риск без исправления | Оценка времени |
|-----------------|-------------------|--------------|--------|----------------------|----------------|
| Review core pipeline | Зрелый код | **Finish** — не рефакторить ядро | Высокий объём тестов | Регрессии | — |
| Monorepo hygiene | Слабый | **Стабилизировать** | README/CI/lockfile | Медленный онбординг | 1–3 д |
| Semantic/visual хвосты | Частично | **Finish** точечно или документировать `unknown` | Не архитектурный тупик | Путаница у пользователя | 2–5 д |
| RL subsystem | Experimental | **Заморозить** для MVP продукта | Не нужен для core value | Отвлечение ресурсов | — |
| homework package | Отдельный трек | **Finish** документацию данных | gitignore vs README | ML-трек стопорится | 1 д |

### Вердикт

**Finish MVP first** + **стабилизация** инфраструктуры репозитория (не redesign).

### Do Not Refactor Yet

- `review_service.py` и связанный пайплайн — без сильной причины и тестового покрытия изменений.
- Критерии JSON maps — пока нет автоматизированной миграции контента критериев.

### Must Stabilize Before MVP

- Публичный доступ: auth флаги для write/debug.
- CI в корне + корневой README.
- Решение по `data/` для homework или правка README.

---

## MVP Roadmap

См. `MVP_ROADMAP.md`.

---

## Time Estimate

### Сценарии

| Сценарий | Условия | Оценка времени | Риски |
|----------|---------|------------------|-------|
| Оптимистичный | 1 опытный dev, только review MVP, без публичного prod | **5 чел·дней** (~**1 календарная неделя**) | Занижение тестов на staging |
| Реалистичный | + корневой CI/README, lockfile, smoke E2E, staging auth | **10 чел·дней** (~**2 недели**) | Неучтённые интеграции |
| Пессимистичный | + публичный prod hardening, мониторинг, юридический privacy review | **20+ чел·дней** (~**4–6 недель**) | Внешние зависимости, compliance |

### По блокам

| Блок работ | Что входит | Оценка | Критичность |
|------------|------------|--------|-------------|
| Monorepo / docs | README, CI root | 1–2 д | High |
| Frontend | lockfile, smoke | 0.5–1 д | Medium |
| Backend | уже близко | 0.5–2 д багфиксы | High |
| Auth / security staging | Supabase, флаги | 1–3 д | High для prod |
| DB / migrations | проверка чистого старта | 0.5 д | Medium |
| Интеграции | LLM/DataLens опционально | 1–5 д | Low для MVP |
| Тесты / CI | починка пути workflow | 0.5–1 д | High |
| Деплой | не специфицирован | Unknown | — |
| homework data policy | gitignore vs README | 1 д | Medium для ML |

### Confidence Level

**Low–Medium.** Причины: один git-коммит; нет истории issues; не запускались install/build/test в этой аудит-сессии.

---

## Next 10 Tasks

См. `NEXT_10_TASKS.md`.

---

## Recommended Next Actions

1. Выполнить задачи **1–3** из `NEXT_10_TASKS.md`.
2. Прогнать `pytest` локально в `review_assistant_repo` после фикса CI.
3. Зафиксировать политику публичного staging (auth).

---

## Appendix: Evidence

| Категория | Ссылка / объект |
|-----------|-----------------|
| Commit | `c2d90a451c3fb2a2e7fae674dfdf70e0a9010dfa` |
| Review README | `review_assistant_repo/README.md` |
| ML README | `homework_reviewer_llm/README.md` |
| Entry point | `review_assistant_repo/app/main.py` |
| pyproject | `review_assistant_repo/pyproject.toml`, `homework_reviewer_llm/pyproject.toml` |
| Env template | `review_assistant_repo/.env.example` |
| Docker | `review_assistant_repo/Dockerfile`, `docker-compose.yml` |
| CI file (вложенный) | `review_assistant_repo/.github/workflows/ci.yml` |
| Migrations | `review_assistant_repo/alembic/versions/*.py` |
| CHANGELOG | `review_assistant_repo/CHANGELOG.md` |
| Тесты | `review_assistant_repo/tests/`, `homework_reviewer_llm/tests/` |
| Semantic not implemented | `review_assistant_repo/app/analyzers/semantic.py` (ветка return с `note`) |
| Visual not implemented | `review_assistant_repo/app/analyzers/visual.py` |
| Notebook clean | `review_assistant_repo/app/parsers/notebook.py` `clean_notebook` |
| Insert export | `review_assistant_repo/app/exporters/notebook.py` |
| Root gitignore | `.gitignore` (`**/data/`) |
| CODE review docs | `CODE_REVIEW.md`, `CODE_REVIEW_BUG_FOCUSED.md` |

---

## Вывод | Доказательство | Уровень уверенности (сводка)

| Вывод | Доказательство | Уровень |
|--------|----------------|---------|
| Два продукта в одном git | Структура каталогов + два pyproject | High |
| Один коммит в истории | `git log --oneline --all` | High |
| Review — основная ценность | Объём кода, README, тесты | High |
| CI GitHub сомнителен для корня | Нет `.github` в корне; workflow только в подпапке | Medium |
| homework quickstart ломается на data | README пути + `.gitignore` | High |
| Подход к авто-ревью — hybrid | README + `review_service` + optional flags | High |

---

## Специальные блоки

- **Dating / offline events:** признаков **не найдено** — отдельный файл `DATING_EVENT_MVP_READINESS.md` **не создан**.
- **Auto-review:** `AUTO_REVIEW_ENGINE_READINESS.md`.
- **ML/data:** `ML_DATA_READINESS.md`.

---

## Источники, отсутствующие в репозитории

- История git > 1 коммита.
- GitHub Issues / Project board.
- Lockfile frontend.
- `homework_reviewer_llm/data/*` в tracked files.
- Явный production deployment манифест для review API.

Из-за этого **оценки сроков и процесса команды** — менее надёжны; для точности нужны внешние артефакты (board, runbooks, staging URL).
