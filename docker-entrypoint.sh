#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
set -euo pipefail

# The GitHub Actions checkout (/github/workspace) is owned by the host runner
# uid, not this container's — git rejects it as "dubious ownership". Mark all
# repos safe so the agent's git operations work. Best-effort (never fatal).
git config --global --add safe.directory '*' 2>/dev/null || true

# Default: run the mergecraft CLI. GitHub Actions Docker actions pass inputs as
# INPUT_* env vars; the gha command reads them.
if [[ "${1:-}" == "gha" ]] || [[ -n "${GITHUB_ACTIONS:-}" && "${1:-}" == "" ]]; then
  exec mergecraft gha "${@:2}"
fi

exec mergecraft "$@"
