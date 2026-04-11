# Homework Reviewer LLM — эксперимент SFT/QLoRA

Репозиторий для пайплайна: **сырые ДЗ + ревью → санитизация → split → JSONL для SFT → QLoRA в облаке → метрики и MVP-инференс**.

## Структура

| Путь | Назначение |
|------|------------|
| [docs/METRICS.md](docs/METRICS.md) | Описание метрик |
| [schemas/review_output.schema.json](schemas/review_output.schema.json) | JSON Schema ответа v1 |
| [schemas/review_output_v2.schema.json](schemas/review_output_v2.schema.json) | JSON Schema гибридного ответа v2 |
| `src/homework_reviewer_llm/` | Схемы, промпты, санитизация, split, SFT, метрики, guardrails, контрастные примеры |
| `scripts/` | CLI для датасета, SFT, оценки, инференса |
| `training/` | `train_qlora.py`, Docker, sweep-скрипт |
| [templates/blind_review_form.md](templates/blind_review_form.md) | Форма слепого сравнения |
| [experiments/EXPERIMENT_REPORT.md](experiments/EXPERIMENT_REPORT.md) | Шаблон отчёта |

## Установка

```bash
cd homework_reviewer_llm
python -m venv .venv && source .venv/bin/activate
pip install -e .
# для обучения и инференса на GPU (Linux):
pip install -e ".[train]"
```

## 1. Формат сырых данных (JSONL)

Одна строка = один объект полей `RawHomeworkRecord` (см. `src/homework_reviewer_llm/schema.py`). Опционально: `revision_history`, `student_profile`. Шаблон одной записи (для сбора с нуля): [data/templates/raw_homework_record.example.json](data/templates/raw_homework_record.example.json). Демо-набор: [data/samples/raw_homework.jsonl](data/samples/raw_homework.jsonl).

### Ручная выгрузка ревьюера (таблица → JSONL)

1. Скопируйте заголовок из [data/templates/reviewer_manual_export.csv](data/templates/reviewer_manual_export.csv) в Excel / Google Sheets.
2. Заполняйте строки: обязательны `id`, `student_id`, `assignment_id`, `submission_text`, `review_text`, `overall_score`. Длинный текст и переносы строк — внутри одной ячейки (Excel это поддерживает).
3. Сохраните как **CSV UTF-8** (в Excel: «CSV UTF-8 (разделители — запятые)»).
4. Конвертация:

```bash
python scripts/csv_to_raw_jsonl.py --input path/to/reviewers.csv --output data/raw/from_reviewers.jsonl
```

5. Далее — `build_dataset.py` с `--input data/raw/from_reviewers.jsonl`.

Колонка `rubric_scores`: один компактный JSON в строке; в CSV кавычки внутри поля удваиваются (см. пример в шаблоне).

### Локальный пайплайн до SFT (шаги плана одной командой)

После появления **CSV** или **готового raw JSONL** можно сразу получить `processed/*.jsonl` и `sft/train_val_v2.jsonl` (без GPU):

```bash
python scripts/pipeline_local.py --csv path/to/reviewers.csv --workdir runs/exp01 --output-format v2
# или
python scripts/pipeline_local.py --raw-jsonl data/raw/from_reviewers.jsonl --workdir runs/exp01 --output-format v2
```

Опции split совпадают с `build_dataset.py` (`--split-mode`, `--seed`, доли train/val/test и т.д.). Флаг **`--with-contrastive`** добавляет контрастные примеры и файл `sft/train_val_v2_plus_contrastive.jsonl`.

После `pipeline_local` (когда есть `processed/test.jsonl`):

```bash
python scripts/sanity_eval_workdir.py --workdir runs/exp01 --format v2
```

Печать готовой команды обучения (подставляет пути из `workdir`):

```bash
python scripts/print_train_command.py --workdir runs/exp01 --format v2
python scripts/print_train_command.py --workdir runs/exp01 --format v2 --dataset plus_contrastive
```

Дальше — выполнить выведенную команду **в облаке с GPU** (локально на M1 обычно не тянет QLoRA 7B).

## 2. Датасет: санитизация и split

```bash
python scripts/build_dataset.py \
  --input data/samples/raw_homework.jsonl \
  --output-dir data/processed \
  --holdout-assignments-ratio 0.2 \
  --hard-fraction 0.2
```

Появятся `data/processed/train.jsonl`, `val.jsonl`, `test.jsonl`, при необходимости `hard.jsonl`.

**Строгий split** (одновременно непересекающиеся студенты и пулы `assignment_id`; строки вне допустимых пар отбрасываются):

```bash
python scripts/build_dataset.py \
  --input data/samples/raw_homework.jsonl \
  --output-dir data/processed_strict \
  --split-mode strict_both \
  --test-assignment-pool-ratio 0.35 \
  --seed my-seed
```

Нужно **не меньше двух разных** `assignment_id` в данных.

## 3. SFT JSONL

```bash
python scripts/build_sft_jsonl.py \
  --train data/processed/train.jsonl \
  --val data/processed/val.jsonl \
  --output data/sft/train_val.jsonl
```

**Формат v2** (гибрид: `student_feedback` + `reviewer_report` + `factor_analysis` с учётом работы, истории правок и профиля):

```bash
python scripts/build_sft_jsonl.py \
  --train data/processed/train.jsonl \
  --val data/processed/val.jsonl \
  --output data/sft/train_val_v2.jsonl \
  --output-format v2
```

### Контрастные примеры (план п. 3)

Генерация дополнительных диалогов: «плохой JSON → исправь» и варианты с явным предупреждением в user-промпте (`too_soft`, `no_justification`, `vague_recommendations`):

```bash
python scripts/build_contrastive_sft_jsonl.py \
  --input-jsonl data/processed/train.jsonl \
  --output-jsonl data/sft/contrastive_train.jsonl \
  --modes rewrite_bad,inline_warning \
  --kinds too_soft,no_justification,vague_recommendations
```

Для v2 добавьте `--output-format v2`.

Объединение с базовым SFT перед обучением:

```bash
cat data/sft/train_val.jsonl data/sft/contrastive_train.jsonl > data/sft/train_val_plus_contrastive.jsonl
```

## 4. Обучение QLoRA (облако / Docker GPU)

```bash
# один запуск
accelerate launch training/train_qlora.py \
  --model_name Qwen/Qwen2.5-7B-Instruct \
  --dataset_jsonl data/sft/train_val.jsonl \
  --output_dir runs/qlora-run1 \
  --max_steps 500
```

Три эксперимента подряд:

```bash
chmod +x training/run_cloud_sweep.sh
DATA_JSONL=data/sft/train_val.jsonl MODEL_NAME=Qwen/Qwen2.5-7B-Instruct ./training/run_cloud_sweep.sh
```

Docker:

```bash
docker build -f training/Dockerfile.gpu -t hw-reviewer-train .
docker run --gpus all -v "$PWD":/work -w /work hw-reviewer-train \
  accelerate launch training/train_qlora.py \
    --model_name Qwen/Qwen2.5-7B-Instruct \
    --dataset_jsonl data/sft/train_val.jsonl \
    --output_dir runs/docker1 \
    --max_steps 200
```

> **M1:** обучение с `bitsandbytes` 4-bit обычно не поддерживается; используйте облако или полноценный Linux+GPU.

## 5. Оценка

Эталон для метрик строится так же, как при SFT: v1 — `gold_review_to_output_simple`, v2 — `gold_review_to_output_v2`. Подготовьте `pred.jsonl`: по строке `{"id": "...", "raw": "<модельный вывод>"}`.

Проверка конвейера метрик (идеальный «oracle»), **v1**:

```bash
python scripts/make_dummy_predictions.py \
  --gold-jsonl data/processed/test.jsonl \
  --output /tmp/pred_oracle_v1.jsonl
python scripts/evaluate.py \
  --gold-jsonl data/processed/test.jsonl \
  --pred-jsonl /tmp/pred_oracle_v1.jsonl \
  --format v1 \
  --report-json experiments/metrics_oracle_v1.json
```

То же для **v2**:

```bash
python scripts/make_dummy_predictions.py \
  --gold-jsonl data/processed/test.jsonl \
  --output /tmp/pred_oracle_v2.jsonl \
  --output-format v2
python scripts/evaluate.py \
  --gold-jsonl data/processed/test.jsonl \
  --pred-jsonl /tmp/pred_oracle_v2.jsonl \
  --format v2 \
  --report-json experiments/metrics_oracle_v2.json
```

## 6. MVP-инференс

Пакетный прогон тестового split (для `evaluate.py`):

```bash
python scripts/batch_inference.py \
  --model_name Qwen/Qwen2.5-7B-Instruct \
  --adapter_path runs/qlora-run1 \
  --input-jsonl data/processed/test.jsonl \
  --output-jsonl experiments/pred_finetuned.jsonl \
  --output-format v2 \
  --guardrail-stats
```

Одиночный файл:

```bash
python scripts/inference_mvp.py \
  --model_name Qwen/Qwen2.5-7B-Instruct \
  --adapter_path runs/qlora-run1 \
  --submission_file data/samples/submission.txt \
  --assignment_file data/samples/assignment.txt \
  --rubric_file data/samples/rubric.txt \
  --revision_history_file path/to/history.txt \
  --student_profile_file path/to/profile.txt \
  --output-format v2 \
  --guardrails \
  --fail-on-guardrails
```

**Guardrails**: v1 — `validate_review_output`; v2 — `validate_review_output_v2` (три фактора в `factor_analysis`, actionable-шаги для студента, длина `risk_assessment` / `score_justification`). В CLI — `validate_raw_by_format`.

## Проверка по шагам (план v2 + регрессия v1)

Соответствие реализации плану «гибридный развернутый ответ» и удобные точечные прогоны тестов. Рабочий каталог — корень `homework_reviewer_llm`.

**Подготовка:**

```bash
cd homework_reviewer_llm
pip install -e .
```

| Шаг | Содержание | Команда тестов |
|-----|------------|----------------|
| 1 | Схемы v1/v2, поля `revision_history` / `student_profile`, парсеры, `schemas/review_output_v2.schema.json` | `pytest -q tests/test_schema.py` |
| 2 | Промпты v2 и user-блок с факторами (косвенно) | `pytest -q tests/test_sft_format.py::test_record_to_messages_v2_has_hybrid_keys` |
| 3 | `gold_review_to_output_v2`, `record_to_messages` / `record_to_sft_dict` | `pytest -q tests/test_sft_format.py` |
| 4 | Контрастные примеры с `output_format` (в т.ч. v2), guardrails v2 | `pytest -q tests/test_contrastive.py tests/test_guardrails.py` |
| 5 | CLI: `build_sft_jsonl`, сквозной пайплайн с `--output-format v2` | `pytest -q tests/test_pipeline_scripts.py` |
| 5b | `pipeline_local.py`: CSV или raw JSONL → processed → SFT | `pytest -q tests/test_pipeline_local.py` |
| 5c | oracle-метрики, `print_train_command`, контрастный merge | `pytest -q tests/test_post_pipeline_scripts.py` |
| 6 | Метрики v2 (`factor_coverage_rate`, `dual_audience_completeness`) | `pytest -q tests/test_metrics.py` |
| 7 | Регрессия v1 (короткий набор) | см. блок ниже |

Регрессия **v1** (старый формат без обязательных секций v2):

```bash
pytest -q tests/test_schema.py tests/test_sft_format.py::test_record_to_messages_structure \
  tests/test_sft_format.py::test_gold_review_has_valid_shape tests/test_metrics.py::test_evaluate_perfect
```

Опционально — быстрая ручная проверка CLI после сборки датасета:

```bash
python scripts/build_dataset.py --input data/samples/raw_homework.jsonl --output-dir /tmp/hw_proc --seed t1
python scripts/build_sft_jsonl.py --train /tmp/hw_proc/train.jsonl --output /tmp/sft_v2.jsonl --splits train --output-format v2
python -c "import json; L=open('/tmp/sft_v2.jsonl').readline(); o=json.loads(L); a=json.loads(o['messages'][-1]['content']); print('v2_ok' if 'student_feedback' in a else 'fail')"
```

## Тесты

```bash
pip install -e ".[dev]"  # или pytest отдельно
pytest -q
```

Ожидается полный зелёный прогон всех тестов пакета (включая v1 и v2).

## Лицензия и данные

Используйте только данные, на которые у вас есть право обработки; перед обучением выполняйте деперсонализацию (`sanitize.py`).
