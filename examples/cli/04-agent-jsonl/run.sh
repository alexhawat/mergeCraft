#!/usr/bin/env bash
set -euo pipefail

EXAMPLE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${EXAMPLE_DIR}/../../.." && pwd)"
LIB="${REPO_ROOT}/scripts/cli_example_lib"
# shellcheck source=../../../scripts/cli_example_lib/mergecraft_root.sh
source "${LIB}/mergecraft_root.sh"

set +e
mergecraft_invoke "${EXAMPLE_DIR}" review \
  --diff "${EXAMPLE_DIR}/patch.diff" \
  --cwd "${EXAMPLE_DIR}" \
  --agent \
  --dry-run > "${EXAMPLE_DIR}/agent.jsonl" 2>/dev/null
review_exit=$?
set -e

python3 "${EXAMPLE_DIR}/read_agent_jsonl.py" < "${EXAMPLE_DIR}/agent.jsonl" \
  > "${EXAMPLE_DIR}/verdict.txt"

echo "${review_exit}" > "${EXAMPLE_DIR}/exit-code.txt"

# Documented exit-code table for orchestrators (D12 — offline dry-run stays on 0).
cat > "${EXAMPLE_DIR}/exit-code-map.txt" <<'EOF'
0 pass
10 findings
11 blocked
12 failed
20 inconclusive
30 configuration
40 infra
50 timeout
2 usage
EOF
