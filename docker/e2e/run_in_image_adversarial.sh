#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Run the W4 adversarial suite inside the built Action image (W11.2).
# The production image is the real containment boundary — not the host venv.
#
# Scope = W4 shell × push + containment/credential/trust invariants.
# W9 process-tree tests stay on the host CI job (need a writable pytest tmp
# layout that conflicts with a :ro workspace mount).
set -euo pipefail

IMAGE="${1:?image tag required}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

echo "» in-image adversarial suite: ${IMAGE}"
docker run --rm \
  -v "${ROOT}:/workspace:ro" \
  -w /workspace \
  --entrypoint /bin/bash \
  "${IMAGE}" \
  -lc '
set -euo pipefail
# Install only the test runner into the image venv (product code stays
# the baked /opt/mergecraft install — that is the containment boundary).
uv pip install --python /opt/mergecraft/.venv/bin/python \
  "pytest==9.0.3" "pytest-asyncio==1.3.0"
export PYTHONPATH=/workspace
export PYTEST_ADDOPTS="-p no:cacheprovider"
/opt/mergecraft/.venv/bin/python -m pytest \
  tests/security/test_shell_push_matrix.py \
  tests/security/test_containment.py \
  tests/security/test_containment_escapes.py \
  tests/security/test_credential_theft.py \
  tests/security/test_credentials.py \
  tests/security/test_trust_ordering.py \
  tests/security/test_trust_ordering_attacks.py \
  -q --tb=short -m "not integration"
'

echo "» in-image adversarial suite OK"
