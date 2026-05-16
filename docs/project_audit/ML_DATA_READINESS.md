# ML / Data Readiness (`homework_reviewer_llm`)

## Таблица компонентов

| ML/Data компонент | Статус | Где находится | Риск | Что нужно до MVP |
|-------------------|--------|---------------|------|------------------|
| Источники данных | Partial | `schema.py`, README (CSV → JSONL) | README ссылается на файлы в `data/`, **не в git** (`.gitignore`) | Политика данных + примеры в репо |
| Схемы данных | Done | `schemas/*.json`, `schema.py` | — | — |
| Pipeline preprocessing | Done | `sanitize.py`, `build_dataset.py`, `pipeline_local.py` | Зависимость от входных данных | Валидные входы |
| Feature / SFT formatting | Done | `sft_format.py`, `contrastive.py` | — | — |
| Train/val/test split | Done | `split.py`, флаги strict | Нужно ≥2 assignment_id для strict | Документировано в README |
| Training | Done (код) | `training/train_qlora.py`, Docker GPU | M1/Darwin без 4-bit; облако нужно | Инфра |
| Inference MVP | Done (код) | `scripts/inference_mvp.py` | Требует `[train]` deps + веса | GPU/модель |
| Evaluation | Done | `scripts/evaluate.py`, `metrics.py` | Нужны gold + pred JSONL | Данные |
| Метрики | Done | `docs/METRICS.md`, `metrics.py` | Интерпретация — на стороне продукта | — |
| Notebooks / отчёты | Partial | `experiments/EXPERIMENT_REPORT.md` шаблон | Пустой каркас | Заполнение вручную |
| Reproducibility | Partial | Нет закоммиченных `runs/` (gitignore) | Воспроизводимость экспериментов вне git | Внешнее хранилище артефактов |
| Data leakage | Unknown | `split.py` strict режимы | Риск при неверном split | Ревью методологии — вне автоматического аудита |
| Model artifacts | Missing в git | `runs/`, веса не коммитятся | Ожидаемо | Политика версионирования моделей |
| Experiment tracking | Missing | Нет MLflow/W&B в pyproject | Нет централизованного трекинга | Post-MVP |
| Deployment inference API | Missing | Нет сервиса в пакете | Только скрипты | Интеграция в review app — отдельная задача |

---

## Оценки

| Вопрос | Ответ | Уверенность |
|--------|--------|-------------|
| Воспроизвести метрики на синтетике | Да, через `make_dummy_predictions` + `evaluate` при наличии test JSONL | Medium |
| Запустить обучение | Код есть; нужен Linux+GPU и зависимости `[train]` | High |
| Запустить инференс | Скрипт есть; нужны веса и окружение | High |
| Данные / mock | Встроенные тесты частично без внешних файлов; полный pipeline — **samples в README не в репо** | High |
| Утечка данных | Строгий split поддержан кодом; реальный риск зависит от данных пользователя | Low (нужен доменный аудит) |
| Метрики качества | Описаны в `docs/METRICS.md` | High |

---

## Вывод | Доказательство | Уровень

| Вывод | Доказательство | Уровень |
|--------|----------------|---------|
| Пакет — offline ML pipeline, не online-сервис | Нет FastAPI в `homework_reviewer_llm` | High |
| Критический разрыв quickstart — `data/` в gitignore | Корневой `.gitignore`, README пути | High |
