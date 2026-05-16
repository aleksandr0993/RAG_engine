# Demo Readiness

## Таблица demo-сценариев

| Demo-сценарий | Готовность | Что работает | Что мешает показать | Что нужно исправить |
|---------------|------------|--------------|---------------------|---------------------|
| Rules-only review ноутбука (без LLM) | Mostly done | Парсеры, rule engine, export; пример `examples/sample_notebook.ipynb` в репо | Нужен запущенный API + один `curl`/форма | Следовать `review_assistant_repo/README.md` Upload examples |
| Полный UI flow (upload → project) | Partially done | Next.js страницы существуют | Нужны `npm install`, `NEXT_PUBLIC_API_URL`, CORS если другой origin | Настроить CORS в `.env`; зафиксировать lockfile |
| DataLens capture demo | Stub / mock level для «из коробки» | Код capture | `ENABLE_BROWSER_CAPTURE=false` по умолчанию; нужен Playwright | Включить флаги + `playwright install` |
| LLM-enhanced review | Partially done | Клиент LLM, circuit breaker | Нужен `LLM_API_KEY` | Выдать ключ демо-окружения |
| RL training demo | Post-MVP / optional | Endpoints, worker script | Тяжёлые deps; `ENABLE_RL_ENGINE=false` | Не включать в короткое демо без подготовки |
| homework_reviewer_llm pipeline | Partially done | Код + тесты на синтетике | Нет `data/samples` в git | Добавить данные или инструкцию |
| Student assistant | Unknown без запуска | API + static HTML | Требует проверки в рантайме | Smoke после поднятия API |

---

## Вердикт

**Demo possible with preparation**

Обоснование: backend сценарий с примерами из `examples/` **документирован** и не требует LLM; для «красивого» UI и DataLens нужна дополнительная подготовка окружения.

**Не готово как:** Ready for demo без оговорок — из-за отсутствия корневого README, lockfile frontend, и опциональных тяжёлых подсистем.

---

## Minimal Demo Script (3–7 минут)

1. **Подготовка (до демо):** `cd review_assistant_repo`, venv, `pip install -e .[dev]`, `cp .env.example .env`, убедиться что `ENABLE_LLM=false` (по умолчанию).
2. **Старт:** `uvicorn app.main:app --reload` — открыть `http://127.0.0.1:8000/docs`.
3. **Загрузка:** выполнить `POST /api/v1/projects/upload` с `examples/sample_notebook.ipynb` и подходящими полями формы (`criteria_map_code`, `style_profile_code` — см. README «Default maps»).
4. **Ревью:** `POST /api/v1/projects/{project_id}/review` — дождаться `done`.
5. **Результат:** `GET /api/v1/projects/{project_id}/review_result` — показать `final_verdict`, кратко findings.
6. **Экспорт (опционально):** `GET .../export/reviewed_notebook` — скачать файл и открыть в Jupyter.
7. **Итог:** подчеркнуть, что LLM и browser capture **намеренно выключены** для стабильности демо.

**Доказательства путей:** `review_assistant_repo/README.md` (Upload examples, Default maps), `examples/sample_notebook.ipynb`.

---

## Вывод | Доказательство | Уровень уверенности

| Вывод | Доказательство | Уровень |
|--------|----------------|---------|
| CLI/API демо реалистично без LLM | README + examples | High |
| UI демо требует доп. шагов | frontend `package.json`, нет lockfile | Medium |
