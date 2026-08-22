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

git add .
git commit -q -m "baseline"

cat > src/calculator.py <<'PY'
"""Tiny module changed in the local-diff example."""

from __future__ import annotations


def add(left: int, right: int) -> int:
    return left + right + 1
PY

{
  echo "command=mergecraft review --dry-run"
  mergecraft_invoke "${EXAMPLE_DIR}" review --dry-run --cwd "${WORKDIR}" 2>&1 \
    | python3 "${LIB}/normalize.py"
} > "${EXAMPLE_DIR}/review-prompt.txt"

echo "0" > "${EXAMPLE_DIR}/exit-code.txt"
