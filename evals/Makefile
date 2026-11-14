# Operator-only benchmark targets. Run from the project with make -C evals.
UV ?= uv
UV_PROJECT_ENVIRONMENT ?= $(abspath ../.venv-dev)
export UV_PROJECT_ENVIRONMENT

.PHONY: check test detection-run detection-summarize detection-context-sha256

check:
	cd .. && $(UV) run --no-sync ruff check evals/repeated_detection.py evals/tests
	cd .. && $(UV) run --no-sync ruff format --check evals/repeated_detection.py evals/tests
	cd .. && $(UV) run --no-sync mypy evals/repeated_detection.py
	$(MAKE) test

test:
	cd .. && $(UV) run --no-sync python -m pytest -p tests.support.hermetic evals/tests -p no:cacheprovider -q

detection-run:
	cd .. && $(UV) run --no-sync python -m evals.repeated_detection run "$(PROTOCOL)" "$(RESULTS)"

detection-summarize:
	@cd .. && $(UV) run --no-sync python -m evals.repeated_detection summarize "$(PROTOCOL)" "$(RESULTS)"

detection-context-sha256:
	@cd .. && $(UV) run --no-sync python -m evals.repeated_detection context-sha256 "$(CONTEXT)"
