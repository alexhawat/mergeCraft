.DEFAULT_GOAL := help

UV ?= $(shell command -v uv 2>/dev/null || echo $(HOME)/.local/bin/uv)
RUFF ?= $(UV) run ruff
MYPY ?= $(UV) run mypy
PYTEST ?= $(UV) run pytest
MERGECRAFT_PYTEST_JOBS ?= auto
PYTEST_XDIST := $(if $(filter 0,$(MERGECRAFT_PYTEST_JOBS)),,$(if $(MERGECRAFT_PYTEST_JOBS),-n $(MERGECRAFT_PYTEST_JOBS),))
BANDIT ?= $(UV) run bandit
PIP_AUDIT ?= $(UV) run pip-audit
PIP_AUDIT_CACHE ?= $(CURDIR)/.cache/pip-audit
PRE_COMMIT ?= $(UV) run pre-commit

.PHONY: help setup install lockcheck lint format typecheck pyright test security \
	precommit build ci ci-static ci-steps ci-resume ci-reset catalog-check docker-build clean \
	examples example-workflows-check

help: ## Show this help
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z0-9_-]+:.*?## / {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

ensure-uv: ## Install uv on PATH when missing
	@if [ -x "$(UV)" ] || command -v uv >/dev/null 2>&1; then exit 0; fi
	@echo "uv not found — installing via astral.sh/install.sh ..."
	curl -LsSf https://astral.sh/uv/install.sh | sh
	@test -x "$(HOME)/.local/bin/uv" || (echo "uv install failed" >&2; exit 1)

setup: ensure-uv ## Fresh checkout: sync deps and pre-commit hooks
	$(UV) sync --extra dev
	@if [ -n "$${CI}$${MERGECRAFT_SKIP_PRECOMMIT}" ]; then \
	  echo "skipping pre-commit install (CI / MERGECRAFT_SKIP_PRECOMMIT)"; \
	else \
	  $(PRE_COMMIT) install; \
	  $(PRE_COMMIT) install --hook-type commit-msg; \
	fi

install: ## Sync dev environment after dependency changes
	$(UV) sync --extra dev

lockcheck: ## Fail if uv.lock is out of date
	$(UV) lock --check

lint: ## Ruff check + formatting + loguru-only
	$(RUFF) check src tests scripts
	$(RUFF) format --check src tests scripts
	$(UV) run python scripts/check_loguru_only.py

format: ## Auto-format with Ruff
	$(RUFF) format src tests scripts
	$(RUFF) check --fix src tests scripts

typecheck: ## mypy strict
	$(MYPY) src/mergecraft

pyright: ## Supplemental Pyright pass
	$(UV) run pyright src/mergecraft

catalog-check: ## Manifest fixture/doc/severity gate (C5/C6)
	$(UV) run python -m mergecraft.analyzers.catalog_docs

PYTEST_SPLIT := $(if $(MERGECRAFT_TEST_SPLITS),--splits $(MERGECRAFT_TEST_SPLITS) --group $(MERGECRAFT_TEST_GROUP) --splitting-algorithm least_duration,)

test: ## Unit tests
	$(PYTEST) tests -v --tb=short --strict-markers -m "not integration" $(PYTEST_XDIST) $(PYTEST_SPLIT) \
		--randomly-seed=$${MERGECRAFT_PYTEST_RANDOM_SEED:-424242}

security: ## Bandit (medium+) + dependency audit
	$(BANDIT) -c pyproject.toml -ll -r src/mergecraft
	@for attempt in 1 2 3; do \
	  if $(PIP_AUDIT) --vulnerability-service=osv --timeout 60 --cache-dir $(PIP_AUDIT_CACHE); then \
	    exit 0; \
	  fi; \
	  echo "pip-audit attempt $$attempt failed; retrying in 5s..." >&2; \
	  sleep 5; \
	done; \
	echo "pip-audit failed after 3 attempts" >&2; exit 1

precommit: ## Run pre-commit on all files
	$(PRE_COMMIT) run --all-files

build: ## Build wheel/sdist
	$(UV) build

examples: ## Render example workflow YAML from templates
	$(UV) run python scripts/render_example_workflows.py

example-workflows-check: ## Fail when committed example workflows drift from templates
	$(UV) run python scripts/render_example_workflows.py --check

ci-static: lockcheck lint typecheck pyright catalog-check build example-workflows-check ## Static/build tier
	@echo "ci-static OK"

# Ordered expansion of `make ci`, consumed by the resumable runner (scripts/ci_resume.sh).
CI_STEPS := lockcheck lint typecheck pyright catalog-check build security test

ci-steps: ## Print the ordered `make ci` step list (consumed by ci-resume)
	@echo $(CI_STEPS)

ci-resume: ## Resumable gate: run ci steps in order, checkpoint passes, stop at first failure, resume on re-run
	@chmod +x scripts/ci_resume.sh 2>/dev/null || true
	@./scripts/ci_resume.sh

ci-reset: ## Clear the ci-resume checkpoint (start the gate over)
	@chmod +x scripts/ci_resume.sh 2>/dev/null || true
	@./scripts/ci_resume.sh --reset

ci: ci-static security test ## Full gate
	@echo "ci OK"

docker-build: ## Build action Docker image
	docker build -t mergeCraft:local -f Dockerfile .

clean: ## Remove caches and build artifacts
	rm -rf .venv dist build .mypy_cache .ruff_cache .pytest_cache htmlcov coverage.xml .cache
