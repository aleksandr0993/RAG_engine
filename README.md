# RAG_engine (monorepo)

Этот репозиторий содержит **два независимых Python-пакета**. Имя каталога `RAG_engine` — **условное**: отдельного запускаемого сервиса с таким именем нет; **RAG / retrieval** — опциональная подсистема внутри Review Assistant.

| Пакет | Назначение | Подробности |
|--------|------------|---------------|
| **`review_assistant_repo`** | FastAPI + (опционально) Next.js: гибридное ревью учебных работ (`.ipynb`, SQL, PDF, HTML, DataLens), критерии, экспорт `reviewed.ipynb` | [review_assistant_repo/README.md](review_assistant_repo/README.md) |
| **`homework_reviewer_llm`** | Офлайн-пайплайн: сырые данные → санитизация → split → JSONL для SFT/QLoRA, скрипты обучения и оценки | [homework_reviewer_llm/README.md](homework_reviewer_llm/README.md) |

## Версии Python

- **Review Assistant:** Python **3.11+** (`review_assistant_repo/pyproject.toml`).
- **Homework Reviewer LLM:** Python **3.10+** (`homework_reviewer_llm/pyproject.toml`).

В корне есть [`.python-version`](.python-version) (**3.11**) — для инструментов вроде `pyenv` / `asdf`; пакет `homework_reviewer_llm` при необходимости можно держать на 3.10 в отдельном venv.

## Быстрый старт: Review Assistant (API)

```bash
cd review_assistant_repo
python3.11 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
cp .env.example .env
uvicorn app.main:app --reload
```

- Документация API: `http://127.0.0.1:8000/docs`
- Смок-тест (нужен уже запущенный API):  
  `bash scripts/smoke_notebook_review.sh`  
  или с другим хостом: `REVIEW_API_BASE=http://127.0.0.1:8000 bash scripts/smoke_notebook_review.sh`

## Быстрый старт: Next.js frontend (опционально)

```bash
cd review_assistant_repo/frontend
npm ci
cp .env.local.example .env.local   # при необходимости
npm run dev
```

`NEXT_PUBLIC_API_URL` по умолчанию указывает на `http://127.0.0.1:8000`. При другом origin для API задайте CORS в `.env` бэкенда (см. README пакета).

## Быстрый старт: Homework Reviewer LLM

```bash
cd homework_reviewer_llm
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
pytest tests/ -q
```

Шаблоны и демо-файлы, **закоммиченные в репозиторий**, лежат в [`homework_reviewer_llm/fixtures/`](homework_reviewer_llm/fixtures/) (каталог `data/` в рабочей копии по-прежнему для локальных прогонов и **игнорируется git** — см. корневой `.gitignore`).

## CI

GitHub Actions для всего монорепозитория: [`.github/workflows/ci.yml`](.github/workflows/ci.yml) (backend в `review_assistant_repo`, frontend lint, тесты `homework_reviewer_llm`).

## Документация аудита

Сводка по состоянию проекта: [docs/project_audit/PROJECT_AUDIT_REPORT.md](docs/project_audit/PROJECT_AUDIT_REPORT.md).
