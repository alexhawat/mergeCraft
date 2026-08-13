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
	examples example-workflows-check bench-review eval-gate \
	test-integration test-integration-live coverage-gate npm-audit workflow-lint

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

# W12.1 / #21 — integration suite joins PR CI. Existing ``@pytest.mark.integration``
# tests self-skip without live secrets/binaries; the scheduled workflow injects
# secrets so the same marker becomes the live-provider release precondition.
# The ``live`` marker is registered for future narrowing by test-creator.
test-integration: ## Integration tests (PR CI; self-skip without live secrets)
	$(PYTEST) tests -v --tb=short --strict-markers -m "integration" $(PYTEST_XDIST) \
		--randomly-seed=$${MERGECRAFT_PYTEST_RANDOM_SEED:-424242}

test-integration-live: ## Live-provider integration (scheduled / release precondition)
	@provider="$${MERGECRAFT_LIVE_PROVIDER:-}"; \
	if [ "$${MERGECRAFT_ALLOW_MISSING_LIVE_CREDS:-}" != "1" ]; then \
	  missing=""; \
	  case "$$provider" in \
	    anthropic) [ -z "$${ANTHROPIC_API_KEY:-}" ] && missing="ANTHROPIC_API_KEY" ;; \
	    openai|codex) [ -z "$${OPENAI_API_KEY:-}" ] && missing="OPENAI_API_KEY" ;; \
	    gemini) [ -z "$${GEMINI_API_KEY:-}" ] && missing="GEMINI_API_KEY" ;; \
	    nous) [ -z "$${NOUS_API_KEY:-}" ] && missing="NOUS_API_KEY" ;; \
	    github) [ -z "$${GITHUB_TOKEN:-}" ] && missing="GITHUB_TOKEN" ;; \
	    *) \
	      for key in ANTHROPIC_API_KEY OPENAI_API_KEY GEMINI_API_KEY NOUS_API_KEY; do \
	        eval "val=\$$$$key"; \
	        [ -z "$$val" ] && missing="$$missing $$key"; \
	      done ;; \
	  esac; \
	  if [ -n "$$missing" ]; then \
	    echo "missing live credentials:$$missing (set secrets or MERGECRAFT_ALLOW_MISSING_LIVE_CREDS=1 for local)"; \
	    exit 1; \
	  fi; \
	fi; \
	contract="tests/integration/test_live_providers.py::test_missing_credential_fails_on_schedule \
	 tests/integration/test_live_providers.py::test_suite_is_inert_on_pull_request \
	 tests/integration/test_live_providers.py::test_response_shape_matches_stream_consumer_contract \
	 tests/integration/test_live_providers.py::test_live_request_is_token_bounded"; \
	case "$$provider" in \
	  anthropic) live_paths="$$contract tests/integration/test_live_providers.py::test_anthropic_minimal_completion" ;; \
	  openai|codex) live_paths="$$contract tests/integration/test_live_providers.py::test_openai_codex_minimal_completion" ;; \
	  gemini) live_paths="$$contract tests/integration/test_live_providers.py::test_gemini_minimal_completion" ;; \
	  nous) live_paths="$$contract tests/integration/test_live_providers.py::test_nous_minimal_completion" ;; \
	  github) live_paths="$$contract tests/integration/test_github_integration.py::test_checkout_and_status_check_roundtrip" ;; \
	  *) live_paths="tests/integration" ;; \
	esac; \
	$(PYTEST) $$live_paths -v --tb=short --strict-markers -m "live" $(PYTEST_XDIST) \
		--randomly-seed=$${MERGECRAFT_PYTEST_RANDOM_SEED:-424242}

coverage-gate: ## Unit tests + coverage floors (global + critical paths)
	$(PYTEST) tests -q --tb=short --strict-markers -m "not integration" \
		--cov=mergecraft --cov-branch --cov-report=term --cov-report=json:coverage.json \
		--randomly-seed=$${MERGECRAFT_PYTEST_RANDOM_SEED:-424242}
	$(UV) run python scripts/check_coverage_floors.py coverage.json

npm-audit: ## npm audit over docker/agent-clis lockfile (W12.3 / #27)
	@command -v npm >/dev/null 2>&1 || { echo "npm not found on PATH" >&2; exit 2; }
	cd docker/agent-clis && npm ci --ignore-scripts && npm audit --audit-level=high

workflow-lint: ## actionlint + zizmor over .github/workflows (W12.3 / #27)
	@chmod +x scripts/workflow_lint.sh
	@./scripts/workflow_lint.sh

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
CI_STEPS := lockcheck lint typecheck pyright catalog-check build example-workflows-check security test

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

REVIEWBENCH_DIR ?= evals/reviewbench

bench-review: ## Run ReviewBench via Harbor (set REVIEWBENCH_DIR to an external corpus)
	@if [ ! -d "$(REVIEWBENCH_DIR)" ]; then \
	  echo "ReviewBench corpus not present at '$(REVIEWBENCH_DIR)'."; \
	  echo "The frozen corpus lives in sevn-bot/tripll (bench/review/) — point at it with:"; \
	  echo "  make bench-review REVIEWBENCH_DIR=../tripll/bench/review"; \
	  echo "See evals/README.md"; \
	  exit 2; \
	fi
	$(UV) run --extra harbor harbor run -d "$(REVIEWBENCH_DIR)" --agent mergecraft.harbor.agent:MergecraftReviewAgent

eval-gate: ## Check eval-bank integrity (structural; see 'mergecraft eval gate --help')
	$(UV) run mergecraft eval gate

docker-build: ## Build action Docker image
	docker build -t mergeCraft:local -f Dockerfile .

clean: ## Remove caches and build artifacts
	rm -rf .venv dist build .mypy_cache .ruff_cache .pytest_cache htmlcov coverage.xml .cache
