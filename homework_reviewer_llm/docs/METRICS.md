# Метрики эксперимента (LLM-ассистент для ревью ДЗ)

## Целевой формат ответа

Модель возвращает **строгий JSON**:

- v1: `schemas/review_output.schema.json`, модель `homework_reviewer_llm.schema.ReviewOutput`;
- v2 (гибрид): `schemas/review_output_v2.schema.json`, модель `homework_reviewer_llm.schema.ReviewOutputV2` (`student_feedback`, `reviewer_report`, `factor_analysis`, `overall_score`).

Обязательные поля:

- `strengths` — список сильных сторон с опциональной привязкой к цитате из работы.
- `issues` — список замечаний (severity: low|medium|high).
- `recommendations` — конкретные шаги для студента (`actionable: true/false`).
- `score_justification` — обоснование итоговой оценки.
- `overall_score` — число в диапазоне, заданном в промпте (по умолчанию 0–100).

Опционально: `rubric_scores` — словарь «критерий → балл/уровень».

## Метрики

### 1. Score MAE (Mean Absolute Error)

Средняя абсолютная ошибка по полю `overall_score` между эталоном (ревьюер) и предсказанием модели.

### 2. Rubric-совпадение

Если в эталоне и предсказании есть `rubric_scores`:

- для числовых значений: MAE по каждому общему ключу, затем среднее;
- для категориальных (строки): доля точных совпадений по ключам.

Если `rubric_scores` отсутствует в эталоне, метрика пропускается (NaN в отчёте).

### 3. Actionability

Доля рекомендаций с `actionable: true` среди всех рекомендаций модели (самодиагностика формата).

Дополнительно можно вручную разметить подвыборку: «рекомендацию можно выполнить без уточнений» — для отчёта ревьюеров.

### 4. JSON validity

Доля ответов, успешно распарсенных в `ReviewOutput` (структурная валидность).

### 5. Guardrails pass rate (опционально)

Доля ответов, для которых `validate_review_output` (v1) или `validate_review_output_v2` (v2) не возвращает ошибок. Логирование: `scripts/batch_inference.py --guardrail-stats` вместе с `--output-format`.

### 6. Метрики v2

При `evaluate.py --format v2` и `evaluate_pairs_v2` дополнительно:

- **factor_coverage_rate** — доля предсказаний, в которых `factor_analysis` содержит все три `factor_id`: `submission`, `revision_history`, `student_profile`.
- **dual_audience_completeness** — доля предсказаний с достаточно заполненными `student_feedback.summary` и `reviewer_report.summary`.

Rubric-метрики для v2 считаются по `reviewer_report.rubric_scores` (если поле есть в эталоне и в предсказании).

## Human-in-the-loop (слепое сравнение)

Шаблон для ревьюеров: `templates/blind_review_form.md`.

Оси: корректность, полезность, тональность (шкала 1–5).
