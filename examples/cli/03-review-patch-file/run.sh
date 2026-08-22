#!/usr/bin/env bash
set -euo pipefail

EXAMPLE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${EXAMPLE_DIR}/../../.." && pwd)"
LIB="${REPO_ROOT}/scripts/cli_example_lib"
# shellcheck source=../../../scripts/cli_example_lib/mergecraft_root.sh
source "${LIB}/mergecraft_root.sh"

{
  echo "command=mergecraft review --diff patch.diff --dry-run"
  mergecraft_invoke "${EXAMPLE_DIR}" review \
    --diff "${EXAMPLE_DIR}/patch.diff" \
    --cwd "${EXAMPLE_DIR}" \
    --dry-run 2>&1 \
    | python3 "${LIB}/normalize.py"
} > "${EXAMPLE_DIR}/review-prompt.txt"

echo "0" > "${EXAMPLE_DIR}/exit-code.txt"
