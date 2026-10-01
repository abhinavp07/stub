.PHONY: setup db migrate api web worker dev lint format test e2e demo-receipts

setup: ## One-time: env file, Postgres, deps, migrations
	@test -f .env || cp .env.example .env
	docker compose up -d --wait
	cd backend && uv sync
	cd infra && uv sync
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

worker: ## SQS worker; needs SQS_QUEUE_URL and STORAGE_MODE=s3 (production setup)
	cd backend && uv run python -m app.worker

dev: db ## API on :8000 and web on :3000, together
	$(MAKE) -j2 api web

lint:
	cd backend && uv run ruff check . && uv run ruff format --check .
	cd frontend && pnpm lint && pnpm format:check && pnpm typecheck
	cd infra && uv run ruff check . && uv run ruff format --check .

format:
	cd backend && uv run ruff check --fix . && uv run ruff format .
	cd frontend && pnpm format
	cd infra && uv run ruff check --fix . && uv run ruff format .

test:
	cd backend && uv run pytest
	cd frontend && pnpm test
	cd infra && uv run pytest

e2e: db ## Playwright happy path; starts its own API (:8100), web (:3100) and receipts_e2e DB
	cd frontend && pnpm exec playwright install chromium && pnpm e2e

demo-receipts: ## Regenerate demo-receipts/ with dates in the current month
	cd backend && uv run python -m scripts.make_demo_receipts
