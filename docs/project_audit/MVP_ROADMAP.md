# MVP Roadmap

**Контекст:** в репозитории два продукта — операционный **Review Assistant** (`review_assistant_repo`) и исследовательский **homework_reviewer_llm**. MVP ниже сфокусирован на **Review Assistant** как основной пользовательской ценности; ML-пакет — отдельные фазы при необходимости.

---

## Phase 0 — Stabilization

Цель: любой разработчик с клоном репозитория может запустить API и (опционально) UI без «археологии».

| Задача | Приоритет | Зависимости | Оценка | Acceptance Criteria |
|--------|-----------|-------------|--------|---------------------|
| Добавить корневой `README.md` с картой монорепо, ссылками на `review_assistant_repo/README.md` и `homework_reviewer_llm/README.md`, явным указанием имени продуктов | P0 | нет | 0.5 д | Файл в корне; команды `cd review_assistant_repo` и `cd homework_reviewer_llm` копируются и работают на чистой машине с установленными Python/Node |
| Починить CI для **корня** GitHub-репозитория: workflow с `defaults.run.working-directory: review_assistant_repo` (или перенос `.github` в корень) | P0 | доступ к GitHub | 0.5–1 д | Push в `main` запускает `ruff`, `mypy`, `pytest`; badge/лог виден в Actions |
| Зафиксировать frontend-зависимости: добавить `package-lock.json` или `pnpm-lock.yaml` в git для `review_assistant_repo/frontend` | P1 | нет | 0.25 д | `npm ci` (или pnpm) в CI/локально воспроизводит дерево без дрейфа |
| Документировать политику данных для `homework_reviewer_llm`: либо исключить `data/templates` из `**/data/` gitignore, либо вынести шаблоны в `homework_reviewer_llm/templates_data/` и обновить README | P1 | решение владельца | 1 д | `pytest` в `homework_reviewer_llm` без ручного создания файлов из README **или** README явно говорит «создайте вручную из примера в доке» |

---

## Phase 1 — Core MVP

Минимальный продукт: загрузка → ревью → просмотр результата → экспорт ноутбука (для ipynb).

| Задача | Приоритет | Зависимости | Оценка | Acceptance Criteria |
|--------|-----------|-------------|--------|---------------------|
| Smoke-проверка E2E сценария по README с `examples/sample_notebook.ipynb` | P0 | Phase 0 частично | 0.5 д | `POST /api/v1/projects/upload` + `POST .../review` + `GET .../review_result` возвращают 2xx; `final_verdict` присутствует |
| Проверить `GET /api/v1/projects/{id}/export/reviewed_notebook` на sample | P0 | предыдущая | 0.25 д | Скачанный `.ipynb` открывается в Jupyter; вставленные markdown-комментарии читаемы |
| Убедиться, что Alembic применяется в чистом окружении (`USE_ALEMBIC_MIGRATIONS=true`) | P1 | DB | 0.25 д | После удаления `.db` и перезапуска таблицы создаются через Alembic без ручного вмешательства |
| Задокументировать минимальный `.env` для демо без LLM и без browser capture | P1 | нет | 0.25 д | Таблица «минимальные переменные» в корневом или пакетном README |

---

## Phase 2 — MVP Polish

| Задача | Приоритет | Зависимости | Оценка | Acceptance Criteria |
|--------|-----------|-------------|--------|---------------------|
| Согласовать «MVP» vs RL: по умолчанию `ENABLE_RL_ENGINE=false`; в корневом README явно «RL не входит в MVP» | P2 | нет | 0.25 д | Документировано |
| Расширить интеграционные тесты для веток `semantic`/`visual` с `not implemented` — либо закрыть логикой, либо явно маркировать в API документации | P2 | продуктовое решение | 2–5 д | Нет «тихих» unknown без объяснения в `metadata_json` для обязательных критериев |
| Student assistant и login flows: smoke тест или чеклист вручную | P2 | frontend running | 1 д | Документированный сценарий в DEMO_READINESS |

---

## Phase 3 — Demo / Launch Readiness

| Задача | Приоритет | Зависимости | Оценка | Acceptance Criteria |
|--------|-----------|-------------|--------|---------------------|
| `docker compose up` из `review_assistant_repo` с приложенным `.env.example` → работающий health | P1 | Docker | 0.5 д | `curl http://127.0.0.1:8000/api/v1/health` — 200 |
| Минимальный demo script (3–7 мин) в `docs/` или README | P1 | Phase 1 | 0.25 д | См. `DEMO_READINESS.md` — скрипт перенесён в репо пользователем при желании |
| Production checklist: `REQUIRE_AUTH_FOR_DEBUG_ROUTES`, Supabase для write | P0 для публичного прод | доступ к секретам | 1 д | Чеклист владельца; не хранить секреты в git (подтверждено grep) |

---

## homework_reviewer_llm (отдельный трек)

| Задача | Приоритет | Оценка | Acceptance Criteria |
|--------|-----------|--------|---------------------|
| Воспроизводимый минимальный `data/samples/raw_homework.jsonl` в репозитории (если политика разрешает) | P1 | 1 д | `pipeline_local` проходит без внешних файлов |
| Документировать облачный GPU как единственный путь для QLoRA | P2 | 0.25 д | README уже частично; ссылка на конкретный провайдер **требует уточнения** |
