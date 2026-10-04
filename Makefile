.PHONY: up down test lint fmt check demo help

# ─── Compose shortcuts ────────────────────────────────────────────────────────

## Start all services (detached)
up:
	docker compose up -d --build

## Stop and remove containers (keep volumes)
down:
	docker compose down

## Stop and remove containers AND volumes (full reset)
clean:
	docker compose down -v --remove-orphans

## Tail logs (optionally: make logs svc=api)
logs:
	docker compose logs -f $(svc)

## Open a psql shell
psql:
	docker compose exec postgis psql -U $${POSTGRES_USER:-parcel} -d $${POSTGRES_DB:-parcelai}

# ─── Quality gates ────────────────────────────────────────────────────────────

## Run Python test suite inside the api container
test:
	docker compose run --rm api pytest backend/tests -v

## Run linters (ruff + black check) inside the api container
lint:
	docker compose run --rm api sh -c "ruff check backend/ && black --check backend/"

## Auto-format Python source
fmt:
	docker compose run --rm api sh -c "ruff check --fix backend/ && black backend/"

## Run mypy type check
typecheck:
	docker compose run --rm api mypy backend/app

## Run all checks (lint + typecheck + test)
check: lint typecheck test

# ─── Demo ─────────────────────────────────────────────────────────────────────

## Seed demo data and run the app (Phase 12)
demo:
	@echo "make demo is not yet implemented — will be wired in Phase 12."
	@echo "Run 'make up' to start all services."

# ─── Help ─────────────────────────────────────────────────────────────────────

help:
	@echo "Usage: make [target]"
	@grep -E '^## ' Makefile | sed 's/## /  /'
