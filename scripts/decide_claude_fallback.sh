#!/usr/bin/env bash
# Decide whether to spend the Claude backstop after a retryable provider failure.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=scripts/lib/provider_verdict_guard.sh
source "${ROOT}/scripts/lib/provider_verdict_guard.sh"

need="true"
# #1009 — a rung that failed failover-eligibly (an expired subscription login,
# say) ran no review: its ``neutral`` packet or check-run is the infra failure
# itself, not a posted verdict, so only failure|success may hold the backstop
# back. ``failover_eligible`` is that rung's action output; it is never
# ``retryable`` — the dead login is not retried, the next vendor is tried.
failover="false"
if [ "${CODEX_OUTCOME:-}" = "failure" ]; then
  [ "${CODEX_FAILOVER_ELIGIBLE:-}" = "true" ] && failover="true"
elif [ "${OPENCODE_GO_OUTCOME:-}" = "failure" ]; then
  [ "${OPENCODE_GO_FAILOVER_ELIGIBLE:-}" = "true" ] && failover="true"
fi
blocks_backstop() {
  if [ "${failover}" = "true" ]; then
    verdict_blocks_codex_fallback "$1"
  else
    verdict_blocks_claude_backstop "$1"
  fi
}
if [ "${failover}" = "true" ]; then
  echo "the failed rung is failover-eligible (no retry of its credential can succeed) — a neutral verdict does not hold the Claude backstop back."
fi
# The workflow ``if:`` already excludes Codex ``outcome == success``; this script
# re-checks so a rung that failed after posting a verdict does not spend Claude.
if [ "${CODEX_OUTCOME:-}" = "success" ]; then
  need="false"
  echo "Codex step outcome=success — not spending the Claude backstop."
else
  packet="$(read_packet CODEX_PACKET)"
  if [ -z "${packet}" ]; then
    packet="$(read_packet OPENCODE_GO_PACKET)"
  fi
  if [ -n "${packet}" ]; then
    verdict="$(verdict_from_packet "${packet}")"
    if packet_is_all_ignored "${packet}"; then
      need="false"
      echo "packet decision.verdict=${verdict} (triage skip: ignorePaths) — every changed file is ignored, so no rung has anything to review; not spending the Claude backstop."
    elif blocks_backstop "${verdict}"; then
      need="false"
      echo "packet decision.verdict=${verdict} — a rung posted a verdict despite failing later; not spending the Claude backstop."
    fi
  fi
  if [ "${need}" = "true" ] && [ "${EVENT_NAME}" = "pull_request_target" ]; then
    latest="$(latest_mergecraft_approval)"
    conclusion="$(discard_baseline_verdict "${latest}")"
    if blocks_backstop "${conclusion}"; then
      need="false"
      echo "mergecraft-approval=${conclusion} — a rung posted a verdict despite failing later; not spending the Claude backstop."
    fi
  fi
fi
if [ "${need}" = "true" ]; then
  if [ "${CODEX_OUTCOME:-}" = "failure" ]; then
    echo "::notice title=mergecraft Claude backstop::Codex failed retryably (opencode-go=${OPENCODE_GO_OUTCOME:-skipped}) and no verdict was found in the evidence packet or mergecraft-approval check-run; retrying with anthropic/claude-sonnet."
  else
    echo "::notice title=mergecraft Claude backstop::OpenCode Go failed retryably (codex=${CODEX_OUTCOME:-skipped}) and no verdict was found in the evidence packet or mergecraft-approval check-run; retrying with anthropic/claude-sonnet."
  fi
fi
echo "need=${need}" >> "${GITHUB_OUTPUT}"
