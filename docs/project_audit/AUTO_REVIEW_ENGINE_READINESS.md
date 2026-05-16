# Auto Review Engine Readiness

Специальный блок для репозитория с признаками **auto-review-engine** (ноутбуки, критерии, RAG, RL, вставка комментариев).  
**Доказательство домена:** `review_assistant_repo/README.md`, `app/services/review_service.py`, `app/parsers/notebook.py`, `app/exporters/notebook.py`, `configs/criteria_maps/*.json`.

---

## Таблица: компонент review engine

| Компонент review engine | Статус | Где находится | Текущая архитектура | Что нужно до MVP |
|-------------------------|--------|---------------|---------------------|------------------|
| Загрузка `.ipynb` | Done | `app/parsers/notebook.py`, `routers/projects.py` | nbformat | — |
| Парсинг ячеек / артефакты | Done | `NotebookParser.parse` | rule + metadata секций | — |
| Удаление старых комментариев ревьюера | Mostly done | `NotebookParser.clean_notebook` | Удаляет ячейки с маркерами ревьюера/мидла; студент с `<div` | Политика «студент» — частичная фильтрация; **уточнить** бизнес-правила |
| Извлечение примеров для обучения / RAG | Done / Optional | `scripts/build_review_training_corpus.py`, `app/retrieval/notebook_training.py` | JSONL из размеченных ноутбуков | Данные вне репо |
| RAG / retrieval | Partially done | `app/retrieval/*`, флаги `ENABLE_RETRIEVAL` | Локальный JSONL + hybrid опционально | Включение и данные |
| Criteria map / шаблоны | Done | `configs/criteria_maps/*.json` | JSON критерии + comment_templates | — |
| Сопоставление с критериями | Done | `review_service` + `RuleEngine` / analyzers | rules + hybrid semantic/visual + optional LLM | Закрыть ветки `not implemented` в semantic/visual |
| Инференс позиций вставки | Done | `anchor_position_idx` → `NotebookCommentInserter` | Вставка **после** anchor (`anchor_idx + 1`) | — |
| Один комментарий на критерий (в смысле вставки) | Mostly done | `review_service.py`: для `ipynb` не-pass добавляется одна вставка на итерацию критерия; `seen_criteria` отсекает дубликаты кодов | Один блок HTML на failing criterion | Дедуп HTML: `comment_dedup.py` |
| Один шаблон — одна вставка на проект | Unknown / N/A | Dedupe по HTML и паре (anchor, html) | `dedupe_notebook_insertions` | Не то же, что «один критерий»; глобальный лимит **не найден** |
| Вставка строго после anchor cell | Done | `app/exporters/notebook.py` `insert_comments` | `cells.insert(anchor_idx + 1, ...)` | — |
| Markdown/HTML комментариев | Done | `app/utils/notebook_html.py` `build_notebook_comment_html` | HTML в markdown cell | — |
| Экспорт `reviewed.ipynb` | Done | `GET .../export/reviewed_notebook`, `NotebookCommentInserter.save` | nbformat.write | — |
| Тестовые ноутбуки | Done | `examples/sample_notebook.ipynb`, тесты API | pytest | — |
| Оценка качества вставки | Partially done | `review_metrics.py`, metadata timeline | Метрики пайплайна | Нет отдельного «golden layout scorer» в явном виде |
| PPO / RL как часть ревью | Post-MVP / Experimental | `app/rl/*`, `routers/rl.py` | SB3 / Gymnasium **отдельно** от основного review | Не смешивать с MVP ревью |
| Фильтрация дубликатов комментариев | Done | `app/services/comment_dedup.py` | По HTML и (anchor, html) | — |
| Отчёт о вставках | Partially done | `CriterionResult` в БД, `findings`, `metadata_json` timeline | Нет единого PDF «отчёт для методиста» | Post-MVP или экспорт JSON |

---

## Фактически реализованный подход

**Hybrid:** правила и эвристики (**rules**, **semantic**, **visual**, **sql_ast** / **sql_semantic**, **notebook_semantic**) + **опциональный LLM** + **опциональный retrieval (RAG-подобный)**.  
**PPO/RL** — **отдельный экспериментальный модуль**, не ядро ревью.

**Доказательства:** `README.md` «Implemented vs scaffold»; `app/rl/` сосуществует с `review_service`.

**Уровень уверенности:** High.

---

## Устаревшие части

**Невозможно подтвердить по текущим файлам** наличие «ветки кода, противоречащей README», без запуска тестов и сравнения с production fork. README версии 0.9.10 согласован с `pyproject.toml` и `app/main.py`.

Ветки анализаторов с `metadata.note == "not implemented"` — **незавершённая логика**, не обязательно «устаревшая».

---

## Auto Review Engine MVP Readiness

End-to-end сценарий:

1. Пользователь передаёт `.ipynb` — **Done** (`POST .../upload`).
2. Система читает notebook — **Done** (`NotebookParser`).
3. Система очищает старые комментарии ревьюера — **Mostly done** (`clean_notebook` по маркерам).
4. Система определяет структуру проекта — **Mostly done** (секции, артефакты; **полнота зависит от критериев**).
5. Система сопоставляет ячейки с критериями — **Done** (через pipeline критериев).
6. Система выбирает комментарии — **Done** (шаблоны + optional LLM).
7. Система выбирает позиции вставки — **Done** (`anchor_position_idx`).
8. Система не дублирует один критерий (в цикле) — **Mostly done** (`seen_criteria`).
9. Вставка после anchor — **Done**.
10. Экспорт `reviewed.ipynb` — **Done**.
11. Отчёт «что и почему» — **Partially done** (findings + metadata; нет единого narrative-отчёта файла).

### Вердикт

**Ready for controlled test** (rules-only, локальный API, пример из `examples/`).

**Not ready** как «полностью автономный production review без человека» — из-за optional LLM, heuristic limits, и открытых веток `unknown`/`not implemented` в semantic/visual.

---

## Готовность к новому студенческому ноутбуку без ручной правки

| Условие | Вердикт |
|---------|---------|
| Ноутбук в рамках поддержанных критерием карт Practicum, без экзотики | **Medium** — вероятно пройдёт пайплайн |
| Требуются сильные semantic/visual задачи из «хвоста» анализаторов | **Low** — возможны `unknown` / ручной разбор |
| Нужен LLM-стиль комментариев | Зависит от ключей и сети — **требует уточнения** |

---

## Вывод | Доказательство | Уровень

| Вывод | Доказательство | Уровень |
|--------|----------------|---------|
| Ядро insert+export реализовано | `exporters/notebook.py`, `review_service.py` | High |
| Очистка старых ревью — по маркерам RU-текста | `notebook.py` REVIEWER_MARKER / tests `test_clean_notebook_strips_reviewer_and_middle` | High |
| Полный RAG — optional | `.env.example` `ENABLE_RETRIEVAL=false` | High |
