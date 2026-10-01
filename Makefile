.PHONY: setup db migrate api web dev lint format test

setup: ## One-time: env file, Postgres, deps, migrations
	@test -f .env || cp .env.example .env
	docker compose up -d --wait
	cd backend && uv sync
	cd frontend && pnpm install
	$(MAKE) migrate

db:
	docker compose up -d --wait

migrate:
	cd backend && uv run alembic upgrade head

api:
	cd backend && uv run uvicorn app.main:app --reload --port 8000

web:
	cd frontend && pnpm dev

dev: db ## API on :8000 and web on :3000, together
	$(MAKE) -j2 api web

lint:
	cd backend && uv run ruff check . && uv run ruff format --check .
	cd frontend && pnpm lint && pnpm format:check && pnpm typecheck

format:
	cd backend && uv run ruff check --fix . && uv run ruff format .
	cd frontend && pnpm format

test:
	cd backend && uv run pytest
	cd frontend && pnpm test
