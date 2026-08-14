# Every target is safe to re-run. `make help` lists them.
.DEFAULT_GOAL := help
.PHONY: help install up down logs seed corpus ingest migrate bootstrap selfcheck audit requirements \
        test test-unit test-integration test-security lint fmt eval datasets \
        web-build web-dev clean

help:               ## Show this list
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[1m%-18s\033[0m %s\n", $$1, $$2}'

install:            ## Install python deps and dev tooling
	pip install -e ".[dev]"

up:                 ## Start the whole stack (postgres, redis, connectors, api, web)
	docker compose up -d --build

down:               ## Stop the stack; add -v to drop volumes
	docker compose down

logs:               ## Follow the API logs
	docker compose logs -f api

migrate:            ## Apply the schema and migrations
	python scripts/migrate.py

seed:               ## Generate and load the seed data
	python -m db.seed.generate && python -m db.seed.load_all

corpus:             ## Render the knowledge corpus from seed data and policy YAML
	python scripts/build_corpus.py

ingest:             ## Chunk, embed and index the corpus (idempotent by content hash)
	python -m retrieval.ingest --all

bootstrap:          ## migrate + seed + corpus + ingest, in the right order
	python scripts/bootstrap.py

selfcheck:          ## Is the demo ready? Prints the fix for anything that is not
	python scripts/selfcheck.py

audit:              ## Map every PRD requirement to its code and its test
	python scripts/spec_audit.py

requirements:       ## Regenerate requirements*.txt from pyproject.toml
	python scripts/sync_requirements.py

test:               ## Everything
	pytest tests -q

test-unit:          ## Pure functions only: no database, no network, no model
	pytest tests/unit -q

test-integration:   ## Needs the running stack
	pytest tests/integration -q -m integration

test-security:      ## ACL, injection and write guards
	pytest tests/security -q

datasets:           ## Regenerate the evaluation datasets
	python eval/generate_datasets.py && python eval/generate_holdout.py

eval:               ## Run the evaluation suites against the PRD targets
	python -m eval.run --json eval-report.json

lint:
	ruff check . && black --check .

fmt:
	ruff check --fix . && black .

web-build:          ## Type-check and bundle the console into web/dist
	cd web && npm install --no-audit --no-fund && npm run build

web-dev:            ## Vite dev server on :3000
	cd web && npm install --no-audit --no-fund && npm run dev

clean:              ## Remove caches and build output
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	rm -rf .pytest_cache .ruff_cache web/dist eval-report.json
