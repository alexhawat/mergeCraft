#!/usr/bin/env bash
# Decide whether to spend the Claude backstop after a retryable provider failure.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=scripts/lib/provider_verdict_guard.sh
source "${ROOT}/scripts/lib/provider_verdict_guard.sh"

need="true"
# The workflow ``if:`` already excludes Codex ``outcome == success``; this script
# re-checks so a rung that failed after posting a verdict does not spend Claude.
if [ "${CODEX_OUTCOME:-}" = "success" ]; then
  need="false"
  echo "Codex step outcome=success — not spending the Claude backstop."
else
  packet="${CODEX_PACKET:-${NOUS_PACKET:-}}"
  if [ -n "${packet}" ]; then
    verdict="$(verdict_from_packet "${packet}")"
    case "${verdict}" in
      failure|success|neutral)
        need="false"
        echo "packet decision.verdict=${verdict} — a rung posted a verdict despite failing later; not spending the Claude backstop."
        ;;
    esac
  fi
  if [ "${need}" = "true" ] && [ "${EVENT_NAME}" = "pull_request_target" ]; then
    latest="$(latest_mergecraft_approval)"
    conclusion="$(discard_baseline_verdict "${latest}")"
    case "${conclusion}" in
      failure|success|neutral)
        need="false"
        echo "mergecraft-approval=${conclusion} — a rung posted a verdict despite failing later; not spending the Claude backstop."
        ;;
    esac
  fi
fi
if [ "${need}" = "true" ]; then
  if [ "${CODEX_OUTCOME:-}" = "failure" ]; then
    echo "::notice title=mergecraft Claude backstop::Codex failed retryably (nous=${NOUS_OUTCOME:-skipped}) and no verdict was found in the evidence packet or mergecraft-approval check-run; retrying with anthropic/claude-sonnet."
  else
    echo "::notice title=mergecraft Claude backstop::Nous failed retryably (codex=${CODEX_OUTCOME:-skipped}) and no verdict was found in the evidence packet or mergecraft-approval check-run; retrying with anthropic/claude-sonnet."
  fi
fi
echo "need=${need}" >> "${GITHUB_OUTPUT}"
