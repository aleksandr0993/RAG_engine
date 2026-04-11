# Релизы Review Assistant Practicum

## 0.9.10

- Опциональный CORS для фронта на другом origin; expose заголовков пагинации списка проектов.

```bash
git tag -a v0.9.10 -m "Release 0.9.10 — optional CORS + pagination expose headers"
git push origin v0.9.10
```

## 0.9.9

- Список проектов: `include_total=false` — без COUNT и без заголовков `X-Total-Count*`.

```bash
git tag -a v0.9.9 -m "Release 0.9.9 — projects list optional total count"
git push origin v0.9.9
```

## 0.9.8

- Список проектов: keyset `cursor` / `X-Next-Cursor`.

```bash
git tag -a v0.9.8 -m "Release 0.9.8 — projects cursor pagination"
git push origin v0.9.8
```

## 0.9.7

- Список проектов: заголовки `X-Total-Count` / `X-Total-Count-Truncated`.

```bash
git tag -a v0.9.7 -m "Release 0.9.7 — projects list X-Total-Count"
git push origin v0.9.7
```

## 0.9.6

- `practicum_stats`: фильтр `practicum_input_channel`; расширенный блок `filters` в JSON.

```bash
git tag -a v0.9.6 -m "Release 0.9.6 — practicum_stats practicum_input_channel filter"
git push origin v0.9.6
```

## 0.9.5

- Список проектов: пагинация `offset`.
- `practicum_stats`: фильтры `source_type`, `status` и блок `filters` в JSON.

```bash
git tag -a v0.9.5 -m "Release 0.9.5 — projects offset, practicum_stats column filters"
git push origin v0.9.5
```

## 0.9.4

- Список проектов: фильтры `source_type`, `status`.
- `practicum_stats`: агрегаты по типу источника, статусу проекта и `final_verdict`.

```bash
git tag -a v0.9.4 -m "Release 0.9.4 — project list filters, practicum_stats breakdowns"
git push origin v0.9.4
```

## 0.9.3

### Состав

- Документация: таблица полей `metadata_json` для Практикума/Revisor, примеры `curl` (upload, фильтр списка, `practicum_stats`).
- API: `GET /api/v1/projects?practicum_input_channel=…` (SQLite / PostgreSQL — фильтр в БД; прочие СУБД — ограниченный скан).
- API: `GET /api/v1/debug/practicum_stats` — агрегаты по последним N проектам.
- Тесты: e2e golden для HTML strong/medium/weak (метаданные после ревью).

### Тег в git

```bash
git tag -a v0.9.3 -m "Release 0.9.3 — Practicum docs, list filter, practicum_stats, golden HTML"
git push origin v0.9.3
```

Подставьте имя удалённого репозитория при необходимости.

### Проверки перед тегом

```bash
pip install -e ".[dev]"
ruff check app tests
mypy app
pytest tests/ -q
python scripts/check_readme_endpoints.py
```
