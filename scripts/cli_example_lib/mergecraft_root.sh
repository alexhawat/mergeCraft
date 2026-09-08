#!/usr/bin/env bash
# Resolve the mergeCraft repo root from any examples/cli/<name>/ run.sh.
mergecraft_repo_root() {
  local here="${1:?}"
  if [[ -n "${MERGECRAFT_EXAMPLE_PROJECT_ROOT:-}" ]]; then
    printf '%s\n' "$MERGECRAFT_EXAMPLE_PROJECT_ROOT"
  else
    (cd "${here}/../../.." && pwd)
  fi
}

mergecraft_invoke() {
  local example_dir="${1:?}"
  shift
  local root
  root="$(mergecraft_repo_root "${example_dir}")"
  uv run --project "${root}" mergecraft "$@"
}
