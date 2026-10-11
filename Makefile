# Developer entry points. Recipes are POSIX sh; on Windows, GNU make runs them with Git's sh.

BACKEND := uv run --directory backend
WEB := npm --prefix web

.DEFAULT_GOAL := help
.PHONY: help up down smoke migrate lint test eval eval-record redteam

help: ## List the available targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "} {printf "  %-12s %s\n", $$1, $$2}'

up: ## Build and start every service, waiting until healthy
	docker compose up --detach --build --wait

smoke: ## Smoke checks against the stack started by `make up` (as CI and deploys do)
	sh deploy/smoke.sh

down: ## Stop every service (data volume kept; `docker compose down -v` drops it)
	docker compose down

migrate: ## Apply database migrations and seed the modality catalogue
	docker compose run --rm migrate

lint: ## Ruff, Mypy strict and ESLint
	$(BACKEND) ruff check .
	$(BACKEND) ruff format --check .
	$(BACKEND) mypy
	$(WEB) run lint

test: ## Backend tests
	$(BACKEND) pytest

eval: ## Evaluation gate on `eval` in cached-strict mode (stub until EF-08)
	$(BACKEND) esfake eval

eval-record: ## Record missing model responses with a budget (stub until EF-08)
	$(BACKEND) esfake eval-record

redteam: ## `redteam/dev` attack suite (stub until EF-17)
	$(BACKEND) esfake redteam
