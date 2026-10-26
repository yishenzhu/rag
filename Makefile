.PHONY: up down logs migrate smoke

up:
	docker compose up -d --build

down:
	docker compose down -v

logs:
	docker compose logs -f api worker

migrate:
	docker compose run --rm migrate

smoke:
	PYTHONPATH=.. .venv/bin/python scripts/smoke.py
