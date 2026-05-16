# Unfinished Work

Источники: grep по репозиторию (исключая `node_modules`), README «Honest limitations», условные `pytest.skip`, отсутствие файлов в git.

## Таблица задач

| Задача | Тип проблемы | Где найдено | Почему важно | Приоритет | Оценка времени |
|--------|--------------|-------------|--------------|-----------|----------------|
| Нет корневого README и единой точки входа для монорепо | Документация / onboarding | Корень репозитория | Новый участник не понимает состав репо | P1 | 0.5–1 д |
| GitHub Actions не в корне репозитория | CI/CD | `review_assistant_repo/.github/workflows/ci.yml` отсутствует в `/RAG_engine/.github` | Регрессии не ловятся на push в типичной настройке | P0–P1 | 0.5–1 д |
| Шаблоны/семплы `homework_reviewer_llm/data/*` не в git | Документация vs .gitignore | `homework_reviewer_llm/README.md` ссылается на `data/templates/...`; корневой `.gitignore` — `**/data/` | Тесты и README шаги частично не воспроизводимы из клона | P1 | 1–2 д (политика: LFS или исключения) |
| Семантический анализ: ветка «unknown» с `note: not implemented` | Частичная реализация | `review_assistant_repo/app/analyzers/semantic.py` (~строки 134–139) | Некоторые критерии не дают осмысленного сигнала | P2 | Зависит от критериев; 1–5 д |
| Визуальный анализ: аналогичный fallback | Частичная реализация | `review_assistant_repo/app/analyzers/visual.py` (grep «not implemented») | То же | P2 | 1–5 д |
| Условно пропускаемые тесты (samples, playwright, sklearn, sb3) | Покрытие / окружение | `homework_reviewer_llm/tests/test_pipeline_local.py` (`skipif`); `review_assistant_repo/tests/test_datalens_capture_fallback.py` и др. | CI может зеленеть без реальных интеграций | P2 | 1–3 д |
| README honest limitations: chart CV, async queue, prod auth, richer RAG | Запланировано явно | `review_assistant_repo/README.md` секция «Honest limitations» | Продуктовый долг | P2–Post-MVP | Недели+ |
| Нет lockfile для frontend в git | Воспроизводимость | `Glob` по `package-lock.json` / `pnpm-lock.yaml` в `frontend/` — **не найдено** в tracked | Дрейф зависимостей | P2 | 0.25 д |
| Issues / project board | Отсутствует | Нет `.github/ISSUE_TEMPLATE`, нет ссылок на issues в docs | Нет трекинга в репо | Unknown | — |

---

## P0 — MVP blockers

- **CI не работает для корня репозитория** (если целевой процесс — GitHub на этом mono-репо): без исправления нет автоматической проверки PR.

*Примечание:* если реальный remote — не GitHub, а зеркало без CI, приоритет снижается (**требует уточнения**).

## P1 — Important before MVP

- Корневой README + явные команды для `review_assistant_repo` и `homework_reviewer_llm`.
- Решение по `data/` для homework пакета (шаблоны в репо или documented download).

## P2 — Post-MVP / Improvements

- Расширение semantic/visual покрытия вместо `not implemented`.
- Очередь задач уровня Celery/Redis, если нагрузка вырастет (уже намечено в README limitations).
- Sentry / полноценный monitoring.

## P3 — Cleanup

- Рассмотреть `console.log` во frontend (в grep по ts **не найдено** в выборке — низкий приоритет до появления).
- Унификация именования корня `RAG_engine` vs фактический продукт «Review Assistant».

---

## Группировка по grep «TODO / FIXME / not implemented»

Прямые `TODO`/`FIXME` в коде **почти не найдены**; значимые маркеры:

- `"note": "not implemented"` в metadata результатов анализаторов — `semantic.py`, `visual.py`.
- Комментарий-заглушка в `config.py`: пример URL с `xxx` — документация, не баг.
