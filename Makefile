.PHONY: up down logs migrate models smoke test loadtest

up:
	docker compose up -d --build

down:
	docker compose down -v

logs:
	docker compose logs -f api worker

migrate:
	docker compose run --rm migrate

models:
	docker compose --profile models up -d --build

smoke:
	PYTHONPATH=.. .venv/bin/python scripts/smoke.py

test:
	PYTHONPATH=.. .venv/bin/python -m pytest -q

loadtest:
	PYTHONPATH=.. .venv/bin/python scripts/loadtest.py
