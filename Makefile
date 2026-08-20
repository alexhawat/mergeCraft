.DEFAULT_GOAL := help

UV ?= $(shell command -v uv 2>/dev/null || echo $(HOME)/.local/bin/uv)
RUFF ?= $(UV) run ruff
# Non-blocking advisory families (#146 / W8) — surfaced in CI via lint-ruff-advisory.
RUFF_ADVISORY_FAMILIES ?= BLE,PTH,PERF,C901
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
	examples example-workflows-check docs docs-check reference-docs reference-docs-check bench-review eval-gate eval-replay \
	bench-detect diagrams diagrams-check \
	test-integration test-integration-live test-otlp-collector coverage-gate npm-audit workflow-lint \
	lint-ruff-advisory hook-pins-check

PIPELINE_D2 := docs/diagrams/pipeline.d2
PIPELINE_LIGHT := assets/diagrams/pipeline-light.svg
PIPELINE_DARK := assets/diagrams/pipeline-dark.svg

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

lint: ## Ruff check + formatting + loguru-only + action-yml-hygiene + hook-pins-check + privilege-drop chown + type-ignore reasons
	$(RUFF) check src tests scripts
	$(RUFF) format --check src tests scripts
	$(UV) run python scripts/check_loguru_only.py
	$(UV) run python scripts/check_cli_consoles.py
	$(MAKE) action-yml-hygiene-check
	$(MAKE) hook-pins-check
	$(UV) run python scripts/check_privilege_drop_chown.py
	$(UV) run python scripts/check_type_ignores.py

action-yml-hygiene-check: ## Fail when an action.yml description embeds a literal ${{ }} expression
	$(UV) run python scripts/check_action_yml_hygiene.py

hook-pins-check: ## Fail when .pre-commit-config.yaml hook revs drift from pyproject.toml pins
	$(UV) run python scripts/check_hook_pins.py

lint-ruff-advisory: ## Ruff advisory families (non-blocking CI; #146)
	$(RUFF) check src tests scripts --select $(RUFF_ADVISORY_FAMILIES)

format: ## Auto-format with Ruff
	$(RUFF) format src tests scripts
	$(RUFF) check --fix src tests scripts

typecheck: ## mypy strict
	$(MYPY) src/mergecraft

pyright: ## Supplemental Pyright pass
	$(UV) run pyright src/mergecraft

catalog-check: ## Manifest fixture/doc/severity gate (C5/C6)
	$(UV) run python -m mergecraft.analyzers.catalog_docs

agents-check: ## Agent registry model/prompt/tool validation gate (AP1)
	$(UV) run python -m mergecraft.agents.catalog_docs

PYTEST_SPLIT := $(if $(MERGECRAFT_TEST_SPLITS),--splits $(MERGECRAFT_TEST_SPLITS) --group $(MERGECRAFT_TEST_GROUP) --splitting-algorithm least_duration,)
test: ## Unit tests
	$(PYTEST) tests -v --tb=short --strict-markers -m "not integration" $(PYTEST_XDIST) $(PYTEST_SPLIT) \
		--randomly-seed=$${MERGECRAFT_PYTEST_RANDOM_SEED:-424242}

# W12.1 / #21 — integration suite joins PR CI. Existing ``@pytest.mark.integration``
# tests self-skip without live secrets/binaries; the scheduled workflow injects
# secrets so the same marker becomes the live-provider release precondition.
# The ``live`` marker is registered for future narrowing by test-creator.
test-integration: ## Integration tests (PR CI; self-skip without live secrets)
	$(PYTEST) tests -v --tb=short --strict-markers -m "integration and not live" \
		--ignore=tests/tracing/test_otlp_collector_e2e.py $(PYTEST_XDIST) \
		--randomly-seed=$${MERGECRAFT_PYTEST_RANDOM_SEED:-424242}

test-integration-live: ## Live-provider integration (scheduled / release precondition)
	@live_selector='-m "live"'; \
	MERGECRAFT_LIVE=1 MERGECRAFT_LIVE_PYTEST_MARKER=live $(UV) run python scripts/check_live_integration_contract.py || exit 1; \
	MERGECRAFT_LIVE=1 MERGECRAFT_LIVE_PYTEST_MARKER=live $(UV) run python scripts/run_live_integration.py || exit 1

test-otlp-collector: ## OTLP collector integration — spans must leave the process (#143)
	$(UV) run --extra tracing python scripts/run_otlp_collector_e2e.py

coverage-gate: ## Unit tests + coverage floors (global + critical paths; xpass ratchet runs via conftest hook)
	$(PYTEST) tests -q --tb=short --strict-markers -m "not integration" \
		--cov=mergecraft --cov-branch --cov-report=term --cov-report=json:coverage.json \
		--randomly-seed=$${MERGECRAFT_PYTEST_RANDOM_SEED:-424242} \
		-rX
	$(UV) run python scripts/check_coverage_ratchet.py coverage.json
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

docs: ## Regenerate generated doc pages (CLI, action ref, docs index)
	$(UV) run python scripts/gen_docs.py

docs-check: ## Fail when generated docs drift
	$(UV) run python scripts/gen_docs.py --check

diagrams: ## Regenerate architecture SVGs from D2 source (requires d2 on PATH)
	@command -v d2 >/dev/null 2>&1 || { echo "d2 not found — install from https://d2lang.com" >&2; exit 1; }
	d2 --theme 0 $(PIPELINE_D2) $(PIPELINE_LIGHT)
	d2 --theme 200 $(PIPELINE_D2) $(PIPELINE_DARK)

diagrams-check: ## Assert committed pipeline SVGs exist and README references them
	@test -s $(PIPELINE_D2) || (echo "missing $(PIPELINE_D2)" >&2; exit 1)
	@test -s $(PIPELINE_LIGHT) || (echo "missing $(PIPELINE_LIGHT)" >&2; exit 1)
	@test -s $(PIPELINE_DARK) || (echo "missing $(PIPELINE_DARK)" >&2; exit 1)
	@rg -q 'assets/diagrams/pipeline-light.svg' README.md
	@rg -q 'assets/diagrams/pipeline-dark.svg' README.md
	@if [ -n "$$MERGECRAFT_REQUIRE_D2" ]; then $(MAKE) diagrams; fi

reference-docs: docs ## Regenerate the README action + CLI reference tables (alias)

reference-docs-check: docs-check ## Fail when README reference tables drift (alias)

ci-static: lockcheck lint typecheck pyright catalog-check agents-check build example-workflows-check docs-check ## Static/build tier
	@echo "ci-static OK"

# Ordered expansion of `make ci`, consumed by the resumable runner (scripts/ci_resume.sh).
CI_STEPS := lockcheck lint typecheck pyright catalog-check agents-check build example-workflows-check docs-check security coverage-gate

ci-steps: ## Print the ordered `make ci` step list (consumed by ci-resume)
	@echo $(CI_STEPS)

ci-resume: ## Resumable gate: run ci steps in order, checkpoint passes, stop at first failure, resume on re-run
	@chmod +x scripts/ci_resume.sh 2>/dev/null || true
	@./scripts/ci_resume.sh

ci-reset: ## Clear the ci-resume checkpoint (start the gate over)
	@chmod +x scripts/ci_resume.sh 2>/dev/null || true
	@./scripts/ci_resume.sh --reset

ci: ci-static security coverage-gate ## Full gate
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

eval-replay: ## Replay eval bank; write versioned result set (operator-triggered; needs live keys for F1)
	$(UV) run mergecraft eval replay-bank

bench-detect: ## Join structural replay + live finding-location detection (#140, B3; needs live keys)
	$(UV) run mergecraft eval bench

docker-build: ## Build action Docker image
	docker build -t mergeCraft:local -f Dockerfile .

clean: ## Remove caches and build artifacts
	rm -rf .venv dist build .mypy_cache .ruff_cache .pytest_cache htmlcov coverage.xml .cache
