.PHONY: init up down logs build backend-rebuild migrate test lint typecheck format seed reset prod backup restore generate-client version-check dev-preflight dev-up dev-down dev-logs dev-health dev-update
# Local developer workstation only (see docs/operations/local-development.md — the
# separate persistent dev-server workflow below never touches compose.override.yml).
# Ensures a fresh clone gets both files `docker compose`/`make up` need without any
# manual copy step beyond what's already documented.
init:
	@test -f .env || cp .env.example .env
	@test -f compose.override.yml || cp compose.override.yml.example compose.override.yml
	docker compose build
up:
	@test -f .env || cp .env.example .env
	@test -f compose.override.yml || cp compose.override.yml.example compose.override.yml
	docker compose up --build -d
down:
	docker compose down
logs:
	docker compose logs -f --tail=200
build:
	docker compose build
backend-rebuild:
	docker compose build api worker scheduler migrate
	docker compose up -d --no-deps api worker scheduler
migrate:
	docker compose run --rm migrate
test:
	pnpm test
	sh infrastructure/scripts/run-tests.sh
lint:
	pnpm lint
	sh infrastructure/scripts/run-tests.sh ruff check mykhaya tests
typecheck:
	pnpm typecheck
	sh infrastructure/scripts/run-tests.sh mypy mykhaya
format:
	pnpm format
	sh infrastructure/scripts/run-tests.sh ruff format mykhaya tests
seed:
	docker compose exec api python -m mykhaya.seed
reset:
	@test -f .env || cp .env.example .env
	@test -f compose.override.yml || cp compose.override.yml.example compose.override.yml
	docker compose down -v
	docker compose up --build -d
prod:
	docker compose -f compose.yml -f compose.production.yml up --build -d
backup:
	sh infrastructure/scripts/backup.sh
restore:
	@test -n "$(FILE)" || (echo "Use make restore FILE=/absolute/path/backup.sql.gz" && exit 1)
	sh infrastructure/scripts/restore.sh "$(FILE)"
generate-client:
	docker compose exec api python -c "import json; from mykhaya.main import app; print(json.dumps(app.openapi()))" > apps/api/openapi.json
version-check:
	python infrastructure/scripts/validate_version.py

dev-preflight:
	sh infrastructure/scripts/dev-deploy.sh preflight

dev-up:
	sh infrastructure/scripts/dev-deploy.sh up

dev-down:
	sh infrastructure/scripts/dev-deploy.sh down

dev-logs:
	sh infrastructure/scripts/dev-deploy.sh logs

dev-health:
	sh infrastructure/scripts/dev-deploy.sh health

dev-update:
	sh infrastructure/scripts/update-dev.sh
