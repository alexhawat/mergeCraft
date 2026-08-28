#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Run lane-A privilege identity + trust-ordering suites inside the action image (AP6 / D14b).
# Host macOS lacks setpriv; root-container behaviour is verified here, not on the host.
set -euo pipefail

IMAGE="${1:?image tag required}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

echo "» in-image privilege suite (root): ${IMAGE}"
docker run --rm \
  -v "${ROOT}:/workspace:ro" \
  -w /workspace \
  --entrypoint /bin/bash \
  "${IMAGE}" \
  -lc '
set -euo pipefail
uv pip install --python /opt/mergecraft/.venv/bin/python \
  "pytest==9.1.1" "pytest-asyncio==1.3.0"
export PYTHONPATH=/workspace
export PYTEST_ADDOPTS="-p no:cacheprovider"
PYTEST=(/opt/mergecraft/.venv/bin/python -m pytest)
STABLE_TESTS=(
  tests/prep/test_prep_fail_closed.py
  tests/security/test_trust_ordering.py
  tests/security/test_trust_ordering_attacks.py
)
# AP1.5 RED markers remain until test-creator reconciles — --runxfail avoids XPASS ratchet.
PRIVILEGE_IDENTITY_TESTS=(tests/utils/test_privilege_identity.py)
run_suite() {
  echo "» pytest as uid=$(id -u)"
  "${PYTEST[@]}" "${STABLE_TESTS[@]}" -q --tb=short -m "not integration"
  "${PYTEST[@]}" "${PRIVILEGE_IDENTITY_TESTS[@]}" --runxfail -q --tb=short -m "not integration"
}
run_suite
echo "» pytest as uid=65534 (nobody)"
runuser -u nobody -- env PYTHONPATH=/workspace PYTEST_ADDOPTS="-p no:cacheprovider" \
  bash -lc "
    ${PYTEST[*]} ${STABLE_TESTS[*]} -q --tb=short -m \"not integration\"
    ${PYTEST[*]} ${PRIVILEGE_IDENTITY_TESTS[*]} --runxfail -q --tb=short -m \"not integration\"
  "
'

echo "» in-image privilege suite OK"
