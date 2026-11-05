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
#   E2E_GITHUB_CONTROL_URL (optional host-side URL; Docker host maps to loopback)
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

python3 "${E2E_DIR}/prepare_fixture.py" --work-dir "${WORK_DIR}" --event "${EVENT_NAME}"
python3 - "${WORK_DIR}/github/event.json" "${E2E_GITHUB_CONTROL_URL:-${API_URL}}" <<'PYCONFIG'
import json
import sys
from urllib.request import Request, urlopen
from urllib.parse import urlsplit
from pathlib import Path
url = urlsplit(sys.argv[2])
# host.docker.internal is installed inside the container, not the Linux runner.
if url.hostname == "host.docker.internal":
    url = url._replace(netloc="127.0.0.1" + (f":{url.port}" if url.port else ""))
request = Request(url.geturl() + "/_e2e/fixture", data=Path(sys.argv[1]).read_bytes(),
                  headers={"Content-Type": "application/json"}, method="POST")
with urlopen(request, timeout=10) as response:
    assert json.load(response)["configured"]
PYCONFIG
HEAD_SHA="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["pull_request"]["head"]["sha"])' "${WORK_DIR}/github/event.json")"
OUTPUT_SCHEMA="$(python3 -c 'import sys,json; sys.path.insert(0,sys.argv[1]); from fake_provider import OUTPUT_SCHEMA; print(json.dumps(OUTPUT_SCHEMA))' "${E2E_DIR}/fake-provider-cli")"

# Fake CLI shims must win over the image's real agent CLIs.
chmod +x "${E2E_DIR}/fake-provider-cli/claude" "${E2E_DIR}/fake-provider-cli/codex"

echo "» E2E: image=${IMAGE} event=${EVENT_NAME} api=${API_URL}"
set +e
ACTION_EXIT=0
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
  -e INPUT_ANALYZERS=auto \
  -e INPUT_OUTPUT_SCHEMA="${OUTPUT_SCHEMA}" \
  -e MERGECRAFT_RUN_TIMEOUT_S=180 \
  -e INPUT_MODEL=anthropic/claude-sonnet \
  -e INPUT_MODEL_PIN=enabled \
  -e ANTHROPIC_API_KEY=sk-e2e-fake-anthropic-key \
  "${IMAGE}" \
  gha || ACTION_EXIT=$?
set -e

# Fork-head pull_request_target + provider credentials must refuse before review
# (lane B D2b). The fixture event is an external fork; credentials stay in env
# so the gate is exercised. mergecraft gha exits 30 (configuration_error).
if [[ "${EVENT_NAME}" == "pull_request_target" ]]; then
  EXPECT_OUTCOME="configuration_error"
  REQUIRE_CHECK_RUNS_ARG=()
  if [[ "${ACTION_EXIT}" -ne 30 ]]; then
    echo "FAIL: fork pull_request_target expected exit 30 (configuration_error), got ${ACTION_EXIT}" >&2
    exit 1
  fi
else
  EXPECT_OUTCOME="passed"
  REQUIRE_CHECK_RUNS_ARG=(--require-check-runs)
  if [[ "${ACTION_EXIT}" -ne 0 ]]; then
    exit "${ACTION_EXIT}"
  fi
fi

python3 "${E2E_DIR}/assert_e2e_outputs.py" \
  --github-output "${WORK_DIR}/github/output" \
  --check-runs-dir "${CHECK_RUNS_DIR}" \
  --expect-outcome "${EXPECT_OUTCOME}" \
  --expected-head-sha "${HEAD_SHA}" \
  "${REQUIRE_CHECK_RUNS_ARG[@]}"

echo "» E2E OK: ${EVENT_NAME}"
