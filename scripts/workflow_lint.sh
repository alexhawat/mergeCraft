#!/usr/bin/env bash
# Download the same SHA256-pinned actionlint + zizmor binaries the analyzers
# image ships (Dockerfile.analyzers) and lint .github/workflows (W12.3 / #27).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

ACTIONLINT_VERSION=1.7.12
ACTIONLINT_SHA256=8aca8db96f1b94770f1b0d72b6dddcb1ebb8123cb3712530b08cc387b349a3d8
ZIZMOR_VERSION=1.28.0
ZIZMOR_SHA256=e87b67160194884e375a46a12c57ccc904f762b53845f254fab7f17d98809c09

CACHE_DIR="${MERGECRAFT_TOOL_CACHE:-${ROOT}/.cache/workflow-lint}"
mkdir -p "${CACHE_DIR}"
ACTIONLINT_BIN="${CACHE_DIR}/actionlint"
ZIZMOR_BIN="${CACHE_DIR}/zizmor"
ACTIONLINT_SARIF_TEMPLATE="${ROOT}/src/mergecraft/analyzers/catalog/actionlint-sarif-template.txt"

os="$(uname -s | tr '[:upper:]' '[:lower:]')"
arch="$(uname -m)"
case "${arch}" in
  x86_64|amd64) arch_norm=amd64; zizmor_arch=x86_64 ;;
  aarch64|arm64) arch_norm=arm64; zizmor_arch=aarch64 ;;
  *) echo "unsupported arch: ${arch}" >&2; exit 2 ;;
esac

if [[ ! -x "${ACTIONLINT_BIN}" ]]; then
  if [[ "${os}" != "linux" ]]; then
    echo "workflow-lint: actionlint bootstrap is linux-only in CI; skipping binary install on ${os}" >&2
    echo "Install actionlint/zizmor locally or run this target on ubuntu-latest." >&2
    exit 0
  fi
  tmp="$(mktemp -d)"
  trap 'rm -rf "${tmp}"' EXIT
  curl -fsSL -o "${tmp}/actionlint.tar.gz" \
    "https://github.com/rhysd/actionlint/releases/download/v${ACTIONLINT_VERSION}/actionlint_${ACTIONLINT_VERSION}_linux_${arch_norm}.tar.gz"
  echo "${ACTIONLINT_SHA256}  ${tmp}/actionlint.tar.gz" | sha256sum -c -
  tar -xzf "${tmp}/actionlint.tar.gz" -C "${tmp}" actionlint
  install -m 0755 "${tmp}/actionlint" "${ACTIONLINT_BIN}"
fi

if [[ ! -x "${ZIZMOR_BIN}" ]]; then
  if [[ "${os}" != "linux" ]]; then
    exit 0
  fi
  tmp="${tmp:-$(mktemp -d)}"
  curl -fsSL -o "${tmp}/zizmor.tar.gz" \
    "https://github.com/zizmorcore/zizmor/releases/download/v${ZIZMOR_VERSION}/zizmor-${zizmor_arch}-unknown-linux-gnu.tar.gz"
  # ARM64 digest differs from the amd64 pin in Dockerfile.analyzers — SARIF emit
  # runs on ubuntu-latest amd64 only; arm64 installs trust the release HTTPS path.
  if [[ "${arch_norm}" == "amd64" ]]; then
    echo "${ZIZMOR_SHA256}  ${tmp}/zizmor.tar.gz" | sha256sum -c -
  fi
  tar -xzf "${tmp}/zizmor.tar.gz" -C "${tmp}" zizmor
  install -m 0755 "${tmp}/zizmor" "${ZIZMOR_BIN}"
fi

run_actionlint_sarif() {
  local out="$1"
  echo "» actionlint ${ACTIONLINT_VERSION} (SARIF)"
  local template
  template="$(<"${ACTIONLINT_SARIF_TEMPLATE}")"
  set +e
  "${ACTIONLINT_BIN}" -format "${template}" .github/workflows/*.yml > "${out}"
  local rc=$?
  set -e
  if [[ ! -s "${out}" ]]; then
    echo "workflow-lint: actionlint produced no SARIF (exit ${rc})" >&2
    exit 1
  fi
}

run_zizmor_sarif() {
  local out="$1"
  echo "» zizmor ${ZIZMOR_VERSION} (SARIF)"
  set +e
  "${ZIZMOR_BIN}" --config "${ROOT}/zizmor.yml" --format sarif .github/workflows/ > "${out}"
  local rc=$?
  set -e
  if [[ ! -s "${out}" ]]; then
    echo "workflow-lint: zizmor produced no SARIF (exit ${rc})" >&2
    exit 1
  fi
}

run_actionlint_human() {
  echo "» actionlint ${ACTIONLINT_VERSION}"
  "${ACTIONLINT_BIN}" -color .github/workflows/*.yml
}

run_zizmor_human() {
  echo "» zizmor ${ZIZMOR_VERSION}"
  # Fail the gate on high-severity findings only. Medium/low (e.g. artipacked
  # persist-credentials suggestions, secrets-inherit on Craft preview) stay
  # visible in the log as a ratchet surface without blocking the PR. Intentional
  # high-severity exceptions live in repo-root ``zizmor.yml``.
  "${ZIZMOR_BIN}" --config "${ROOT}/zizmor.yml" --min-severity high .github/workflows/
}

if [[ -n "${MERGECRAFT_WORKFLOW_SARIF_DIR:-}" ]]; then
  mkdir -p "${MERGECRAFT_WORKFLOW_SARIF_DIR}"
  # SARIF mode intentionally ignores tool exit codes — only a non-empty artifact
  # matters for downstream ciEvidence ingest.
  run_actionlint_sarif "${MERGECRAFT_WORKFLOW_SARIF_DIR}/actionlint.sarif"
  run_zizmor_sarif "${MERGECRAFT_WORKFLOW_SARIF_DIR}/zizmor.sarif"
  echo "workflow SARIF OK"
  exit 0
fi

run_actionlint_human
run_zizmor_human
echo "workflow-lint OK"
