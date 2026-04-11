.PHONY: install run run-rl-worker test lint

install:
	pip install -e .[dev]

run:
	uvicorn app.main:app --reload

run-rl-worker:
	python scripts/run_rl_train_worker.py

test:
	pytest -q
