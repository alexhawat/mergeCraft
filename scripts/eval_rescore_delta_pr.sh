#!/usr/bin/env bash
# Advisory base-vs-head structural replay delta for reviewer-surface PRs (#1164).
set -euo pipefail

BASE_REF="${1:-${GITHUB_BASE_REF:-main}}"
HEAD_REF="${2:-${GITHUB_SHA:-HEAD}}"
RESULTS_DIR="${RESULTS_DIR:-evals/results}"
mkdir -p "$RESULTS_DIR"

merge_base="$(git merge-base "origin/${BASE_REF}" "$HEAD_REF")"
head_commit="$(git rev-parse "$HEAD_REF")"

git checkout --quiet "$merge_base"
uv run mergecraft eval replay-bank --json > "${RESULTS_DIR}/rescore-base.json"

git checkout --quiet "$head_commit"
uv run mergecraft eval replay-bank --json > "${RESULTS_DIR}/rescore-head.json"

uv run mergecraft eval rescore-delta \
  --baseline "${RESULTS_DIR}/rescore-base.json" \
  --candidate "${RESULTS_DIR}/rescore-head.json" \
  --output "${RESULTS_DIR}/rescore-delta-pr.json"

if [[ -n "${GITHUB_STEP_SUMMARY:-}" ]]; then
  {
    echo "## Eval rescore delta (structural, advisory)"
    uv run mergecraft eval rescore-delta \
      --baseline "${RESULTS_DIR}/rescore-base.json" \
      --candidate "${RESULTS_DIR}/rescore-head.json" \
      --output "${RESULTS_DIR}/rescore-delta-pr.json" || true
  } >> "$GITHUB_STEP_SUMMARY"
fi
