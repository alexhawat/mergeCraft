#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Run the Action image against a fixture event + D6 fake provider CLI (W11.1).
#
# Usage:
#   docker/e2e/run_action_e2e.sh <image> <event_name>
#     event_name: pull_request | pull_request_target
#
# Expects mock GitHub API already listening; set:
#   E2E_GITHUB_API_URL   (default http://host.docker.internal:8765)
#   E2E_CHECK_RUNS_DIR   (host path; default docker/e2e/fixtures/check-runs/<event>)
#   E2E_WORK_DIR         (scratch dir for GITHUB_OUTPUT / workspace copy)
set -euo pipefail

IMAGE="${1:?image tag required}"
EVENT_NAME="${2:?event name required (pull_request|pull_request_target)}"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
E2E_DIR="${ROOT}/docker/e2e"
API_URL="${E2E_GITHUB_API_URL:-http://host.docker.internal:8765}"
WORK_DIR="${E2E_WORK_DIR:-$(mktemp -d "${TMPDIR:-/tmp}/mergecraft-e2e.XXXXXX")}"
CHECK_RUNS_DIR="${E2E_CHECK_RUNS_DIR:-${E2E_DIR}/fixtures/check-runs/live}"

mkdir -p "${WORK_DIR}/workspace" "${WORK_DIR}/runner-temp" "${WORK_DIR}/github" "${CHECK_RUNS_DIR}"
# Caller clears check-runs between events when sharing one mock server.

# Fresh fixture workspace (git init so setup_git / safe.directory paths work).
rm -rf "${WORK_DIR}/workspace"
cp -R "${E2E_DIR}/fixtures/repo" "${WORK_DIR}/workspace"
(
  cd "${WORK_DIR}/workspace"
  git init -q -b main
  git config user.email "e2e@example.com"
  git config user.name "e2e"
  git add -A
  git commit -q -m "e2e fixture"
)

EVENT_FILE="${E2E_DIR}/fixtures/events/${EVENT_NAME}.json"
if [[ ! -f "${EVENT_FILE}" ]]; then
  echo "missing event fixture: ${EVENT_FILE}" >&2
  exit 1
fi
cp "${EVENT_FILE}" "${WORK_DIR}/github/event.json"
: >"${WORK_DIR}/github/output"
: >"${WORK_DIR}/github/state"

# Fake CLI shims must win over the image's real agent CLIs.
chmod +x "${E2E_DIR}/fake-provider-cli/claude" "${E2E_DIR}/fake-provider-cli/codex"

echo "» E2E: image=${IMAGE} event=${EVENT_NAME} api=${API_URL}"
docker run --rm \
  --add-host=host.docker.internal:host-gateway \
  -v "${WORK_DIR}/workspace:/github/workspace" \
  -v "${WORK_DIR}/runner-temp:/github/runner-temp" \
  -v "${WORK_DIR}/github:/github/file_commands" \
  -v "${E2E_DIR}/fake-provider-cli:/opt/e2e-shim:ro" \
  -v "${E2E_DIR}/fixtures/events:/opt/e2e-events:ro" \
  -e PATH="/opt/e2e-shim:/opt/mergecraft/.venv/bin:/usr/local/bin:/usr/bin:/bin" \
  -e GITHUB_ACTIONS=true \
  -e CI=true \
  -e GITHUB_WORKSPACE=/github/workspace \
  -e GITHUB_EVENT_PATH=/github/file_commands/event.json \
  -e GITHUB_EVENT_NAME="${EVENT_NAME}" \
  -e GITHUB_REPOSITORY=acme/demo \
  -e GITHUB_API_URL="${API_URL}" \
  -e GITHUB_OUTPUT=/github/file_commands/output \
  -e GITHUB_STATE=/github/file_commands/state \
  -e RUNNER_TEMP=/github/runner-temp \
  -e MERGECRAFT_TEMP_PARENT=/github/runner-temp \
  -e INPUT_PROMPT="E2E fixture review — summarise the PR" \
  -e INPUT_TOKEN=ghs_e2e_fake_token \
  -e INPUT_STATUS_CHECKS=enabled \
  -e INPUT_SHELL=restricted \
  -e INPUT_PUSH=restricted \
  -e INPUT_ANALYZERS=off \
  -e INPUT_MODEL=anthropic/claude-sonnet \
  -e INPUT_MODEL_PIN=enabled \
  -e ANTHROPIC_API_KEY=sk-e2e-fake-anthropic-key \
  "${IMAGE}" \
  gha

python3 "${E2E_DIR}/assert_e2e_outputs.py" \
  --github-output "${WORK_DIR}/github/output" \
  --check-runs-dir "${CHECK_RUNS_DIR}" \
  --expect-outcome passed \
  --require-check-runs

echo "» E2E OK: ${EVENT_NAME}"
