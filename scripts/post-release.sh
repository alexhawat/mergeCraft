#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Bump the tree to the next development version after a successful publish.
#
# This reuses scripts/bump-version.sh so pyproject.toml, server.json and
# uv.lock all move together: a post-release bump that touched pyproject.toml
# alone would turn `lockcheck` and `mcp-server-json-check` red on the next
# commit, which is the same defect the prepare bump was fixed for.
#
# The dev version is a canonical PEP 440 "successor development release":
#
#   0.1.0a3  -> 0.1.0a4.dev0     (likewise b, rc)
#   0.1.0    -> 0.1.1.dev0
#
# `-dev` (the previous scheme) is not canonical PEP 440 and sorts *above* the
# final release it follows.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

# Craft calls this as `bash scripts/post-release.sh '' <released-version>`: the
# first argument is always empty, the version arrives second, and only
# CRAFT_RELEASED_VERSION is exported (Craft keeps PATH/HOME/USER/GITHUB_*/
# RUNNER_* and drops the rest — CRAFT_NEW_VERSION is *not* set). $1 and
# CRAFT_NEW_VERSION stay supported for manual runs.
released="${2:-${1:-${CRAFT_RELEASED_VERSION:-${CRAFT_NEW_VERSION:-}}}}"
if [[ -z "${released}" ]]; then
  echo "post-release.sh: a released version is required (Craft passes it as \$2; or set CRAFT_RELEASED_VERSION)" >&2
  exit 1
fi

dev_version="$(python3 - "$released" <<'PY'
import re
import sys

released = sys.argv[1]
match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)(?:(a|b|rc)(\d+))?", released)
if match is None:
    raise SystemExit(
        f"post-release.sh: not a canonical release version: {released!r}"
    )
major, minor, patch, pre, number = match.groups()
if pre is None:
    print(f"{major}.{minor}.{int(patch) + 1}.dev0")
else:
    print(f"{major}.{minor}.{patch}{pre}{int(number) + 1}.dev0")
PY
)"

bash "$ROOT/scripts/bump-version.sh" "$released" "$dev_version"
echo "Bumped development version to ${dev_version}"
