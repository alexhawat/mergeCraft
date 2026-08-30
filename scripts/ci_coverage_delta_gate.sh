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

base_measure_log="${GITHUB_WORKSPACE}/.ci-base-measure.log"

cleanup() {
  rm -f "${GITHUB_WORKSPACE}/coverage-base.json" 2>/dev/null || true
  rm -f "$base_measure_log" 2>/dev/null || true
  git worktree remove "$worktree" --force 2>/dev/null || true
}
trap cleanup EXIT INT TERM

# Drop a stale worktree left by a prior failed integration run before re-adding.
git worktree remove "$worktree" --force 2>/dev/null || true
git worktree prune 2>/dev/null || true

git fetch origin "${GITHUB_BASE_REF}"
git worktree add "$worktree" "$base_ref"
orig_workspace="$GITHUB_WORKSPACE"
: >"$base_measure_log"
# BASE_WORKTREE_MEASURE_BLOCK — parsed by tests/ci/test_coverage_delta_wrapper.py (D10).
(
  cd "$worktree"
  export GITHUB_WORKSPACE="$worktree"  # #573: base tree reads its own config, not head's
  # The base worktree gets its own fresh venv. `dev` is a
  # [project.optional-dependencies] extra, which `uv run` does not install, so
  # `make coverage-measure` died with "Failed to spawn: pytest" before measuring
  # anything. Sync the extra explicitly.
  #
  # Pin which venv that is, because this sync and the `make` below disagreed
  # otherwise. MCB-23 made the Makefile export
  # `UV_PROJECT_ENVIRONMENT ?= $(CURDIR)/.venv-dev`; this sync runs in a bare
  # shell, so it filled `.venv` while `make coverage-measure` then looked in
  # `.venv-dev` and hit the same "Failed to spawn: pytest" by a new route.
  # Exporting it here settles both halves on one path, and `?=` means the
  # Makefile defers to it — so this also works against an older base tree whose
  # Makefile predates MCB-23 and would otherwise default to `.venv`.
  export UV_PROJECT_ENVIRONMENT="${UV_PROJECT_ENVIRONMENT:-$PWD/.venv-dev}"
  "${UV:-uv}" sync --extra dev --extra tracing
  # Repo-native analyzer tests (#427) require tools/node_modules/.bin; bootstrap
  # only runs on the PR checkout, not this detached base worktree.
  make setup-local-analyzers
  measure_ok=true
  if grep -q '^coverage-measure:' Makefile; then
    if ! make coverage-measure >>"$base_measure_log" 2>&1; then
      measure_ok=false
    fi
  else
    # Pre-TH base trees only ship ``coverage-gate``; inline the measure recipe
    # so the delta gate can compare against the merge base before TH lands.
    if ! "${UV:-uv}" run pytest tests -q --tb=short --strict-markers -m "not integration" \
      --cov=mergecraft --cov-branch --cov-report=term --cov-report=json:coverage.json \
      --randomly-seed="${MERGECRAFT_PYTEST_RANDOM_SEED:-424242}" \
      -rX >>"$base_measure_log" 2>&1; then
      measure_ok=false
    fi
  fi
  if [[ "$measure_ok" == true ]]; then
    cp coverage.json "${orig_workspace}/coverage-base.json"
  fi
)
if [[ ! -f coverage-base.json ]]; then
  base_reason="base coverage measurement failed"
  if [[ -s "$base_measure_log" ]]; then
    base_reason="$(tail -n 5 "$base_measure_log" | tr '\n' ' ' | sed 's/[[:space:]]\+/ /g' | sed 's/^ //;s/ $//')"
  fi
  skip_msg="Coverage delta skipped: base ref ${GITHUB_BASE_REF} could not be measured (${base_reason})."
  echo "warning: ${skip_msg}" >&2
  if [[ "${GITHUB_ACTIONS:-}" == "true" ]]; then
    escaped_msg="${skip_msg//'%'/'%25'}"
    escaped_msg="${escaped_msg//$'\r'/'%0D'}"
    escaped_msg="${escaped_msg//$'\n'/'%0A'}"
    echo "::warning title=Coverage delta skipped::${escaped_msg}" >&2
  fi
  if [[ -n "${GITHUB_STEP_SUMMARY:-}" ]]; then
    {
      echo "### Coverage delta skipped"
      echo "${skip_msg}"
    } >>"$GITHUB_STEP_SUMMARY"
  fi
fi
make coverage-gate
if [[ -f coverage-base.json ]]; then
  uv run python scripts/check_coverage_delta.py coverage.json --base coverage-base.json
fi
