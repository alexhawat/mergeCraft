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
(
  cd "$worktree"
  # The base worktree gets its own fresh .venv. `dev` is a
  # [project.optional-dependencies] extra, which `uv run` does not install, so
  # `make coverage-gate` died with "Failed to spawn: pytest" before measuring
  # anything. Sync the extra explicitly.
  "${UV:-uv}" sync --extra dev
  make coverage-gate
  cp coverage.json "${GITHUB_WORKSPACE}/coverage-base.json"
)
make coverage-gate
if [[ -f coverage-base.json ]]; then
  uv run python scripts/check_coverage_delta.py coverage.json --base coverage-base.json
fi
