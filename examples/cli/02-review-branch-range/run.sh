#!/usr/bin/env bash
set -euo pipefail

EXAMPLE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${EXAMPLE_DIR}/../../.." && pwd)"
LIB="${REPO_ROOT}/scripts/cli_example_lib"
# shellcheck source=../../../scripts/cli_example_lib/mergecraft_root.sh
source "${LIB}/mergecraft_root.sh"

WORKDIR="$(mktemp -d)"
trap 'rm -rf "${WORKDIR}"' EXIT

cp -R "${EXAMPLE_DIR}/." "${WORKDIR}/"
rm -f "${WORKDIR}/run.sh" "${WORKDIR}/README.md"
rm -rf "${WORKDIR}/expected"

cd "${WORKDIR}"
git init -q
git config user.email "cli-example@mergecraft.local"
git config user.name "mergeCraft CLI example"

printf 'v1\n' > src/feature.py
git add .
git commit -q -m "baseline"

cat > src/feature.py <<'PY'
"""Branch-range example — final committed state is v2."""

from __future__ import annotations

FEATURE_VERSION = "v2"
PY
git add .
git commit -q -m "feature"

{
  echo "command=mergecraft review --base HEAD~1 --head HEAD --dry-run"
  mergecraft_invoke "${EXAMPLE_DIR}" review --base HEAD~1 --head HEAD --dry-run --cwd "${WORKDIR}" 2>&1 \
    | python3 "${LIB}/normalize.py"
} > "${EXAMPLE_DIR}/review-prompt.txt"

{
  echo "command=mergecraft review --range HEAD~1..HEAD --dry-run"
  mergecraft_invoke "${EXAMPLE_DIR}" review --range HEAD~1..HEAD --dry-run --cwd "${WORKDIR}" 2>&1 \
    | python3 "${LIB}/normalize.py"
} > "${EXAMPLE_DIR}/review-range.txt"

echo "0" > "${EXAMPLE_DIR}/exit-code.txt"
