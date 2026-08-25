#!/usr/bin/env bash
# Coverage ratchet for integration CI — base worktree + delta gate (#432 / D6).
set -euo pipefail

if [[ "${GITHUB_EVENT_NAME:-}" != "pull_request" ]]; then
  make coverage-gate
  exit 0
fi

: "${GITHUB_BASE_REF:?GITHUB_BASE_REF is required for pull_request coverage delta}"
: "${GITHUB_WORKSPACE:?GITHUB_WORKSPACE is required}"

base_ref="origin/${GITHUB_BASE_REF}"
worktree="${GITHUB_WORKSPACE}/.ci-mergecraft-base-coverage"

cleanup() {
  rm -f "${GITHUB_WORKSPACE}/coverage-base.json" 2>/dev/null || true
  git worktree remove "$worktree" --force 2>/dev/null || true
}
trap cleanup EXIT INT TERM

# Drop a stale worktree left by a prior failed integration run before re-adding.
git worktree remove "$worktree" --force 2>/dev/null || true
git worktree prune 2>/dev/null || true

git fetch origin "${GITHUB_BASE_REF}"
git worktree add "$worktree" "$base_ref"
# BASE_WORKTREE_MEASURE_BLOCK — parsed by tests/ci/test_coverage_delta_wrapper.py (D10).
(
  cd "$worktree"
  # The base worktree gets its own fresh .venv. `dev` is a
  # [project.optional-dependencies] extra, which `uv run` does not install, so
  # `make coverage-measure` died with "Failed to spawn: pytest" before measuring
  # anything. Sync the extra explicitly.
  "${UV:-uv}" sync --extra dev --extra tracing
  # Repo-native analyzer tests (#427) require tools/node_modules/.bin; bootstrap
  # only runs on the PR checkout, not this detached base worktree.
  make setup-local-analyzers
  if grep -q '^coverage-measure:' Makefile; then
    make coverage-measure
  else
    # Pre-TH base trees only ship ``coverage-gate``; inline the measure recipe
    # so the delta gate can compare against the merge base before TH lands.
    "${UV:-uv}" run pytest tests -q --tb=short --strict-markers -m "not integration" \
      --cov=mergecraft --cov-branch --cov-report=term --cov-report=json:coverage.json \
      --randomly-seed="${MERGECRAFT_PYTEST_RANDOM_SEED:-424242}" \
      -rX
  fi
  cp coverage.json "${GITHUB_WORKSPACE}/coverage-base.json"
)
make coverage-gate
if [[ -f coverage-base.json ]]; then
  uv run python scripts/check_coverage_delta.py coverage.json --base coverage-base.json
fi
