# Отчёт эксперимента: LLM-ассистент для ревью ДЗ

## Данные

| Параметр | Значение |
|----------|----------|
| Источник | _описание_ |
| N после фильтров | _число_ |
| Train / Val / Test / Hard | _числа_ |
| Утечки | split по `student_id`, опционально holdout по `assignment_id` / `strict_both` |
| Формат ответа модели | v1 (классический JSON) / **v2** (гибрид: студент + ревьюер + `factor_analysis`) |
| Доля записей с `revision_history` | _доля или «нет в данных»_ |
| Доля записей с `student_profile` | _доля или «нет в данных»_ |

## Конфигурация обучения

| Запуск | Модель | LoRA r/α | LR | steps | seed | SFT JSONL (v1/v2) |
|--------|--------|----------|-----|-------|------|-------------------|
| qlora_seed42_lr2e4 | | | | | | |
| qlora_seed43_lr2e4 | | | | | | |
| qlora_seed42_lr1e4 | | | | | | |

## Метрики (авто)

Заполните после `scripts/evaluate.py` (`--format v1` или `--format v2`).

**v1** — в сводке: `score_mae`, `json_valid_rate`, `rubric_*`, `actionable_rate`.

**v2** — дополнительно: `factor_coverage_rate`, `dual_audience_completeness`.

Пример структуры для отчёта:

```json
{
  "format": "v2",
  "baseline": {
    "score_mae": null,
    "json_valid_rate": null,
    "factor_coverage_rate": null,
    "dual_audience_completeness": null
  },
  "finetuned_best": {
    "score_mae": null,
    "json_valid_rate": null,
    "factor_coverage_rate": null,
    "dual_audience_completeness": null
  }
}
```

## Слепая оценка ревьюеров

Используйте [templates/blind_review_form.md](../templates/blind_review_form.md).

Средние баллы:

- Корректность: A ___, B ___
- Полезность: A ___, B ___
- Тональность: A ___, B ___

Предпочтение: ___

Для v2 уточните в форме: отдельно оценивали ли блок **для студента** и блок **для ревьюера**.

## Выводы и ограничения

- Системные ошибки:
- Следующая итерация датасета:
- Guardrails v2 (доля отклонений по `batch_inference --guardrail-stats`):
