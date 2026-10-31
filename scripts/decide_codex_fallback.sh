#!/usr/bin/env bash
# Decide whether to fall back from OpenCode Go to Codex after a no-verdict OpenCode Go run.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=scripts/lib/provider_verdict_guard.sh
source "${ROOT}/scripts/lib/provider_verdict_guard.sh"

need="false"
opencode_go_packet="$(read_packet OPENCODE_GO_PACKET)"
if [ -n "${opencode_go_packet}" ]; then
  verdict="$(verdict_from_packet "${opencode_go_packet}")"
  reason="$(verdict_reason_from_packet "${opencode_go_packet}")"
  if verdict_blocks_codex_fallback "${verdict}"; then
    echo "packet decision.verdict=${verdict} — OpenCode Go review posted a verdict; not falling back to Codex."
  elif neutral_is_untrusted_tier "${verdict}" "${reason}"; then
    echo "packet decision.verdict=${verdict} (${reason}) — an untrusted-tier run is structurally inert, so a fallback rung cannot change the verdict; not falling back to Codex."
  else
    need="true"
    echo "::notice title=mergecraft Codex fallback::OpenCode Go review posted no verdict in evidence packet (action outcome: ${OPENCODE_GO_OUTCOME}); retrying with openai/gpt-codex."
  fi
elif [ "${EVENT_NAME}" = "pull_request_target" ]; then
  latest="$(latest_mergecraft_approval)"
  conclusion="$(discard_baseline_verdict "${latest}")"
  if verdict_blocks_codex_fallback "${conclusion}"; then
    echo "mergecraft-approval=${conclusion} — OpenCode Go review posted a verdict; not falling back to Codex."
  else
    need="true"
    echo "::notice title=mergecraft Codex fallback::OpenCode Go review posted no verdict (action outcome: ${OPENCODE_GO_OUTCOME}); retrying with openai/gpt-codex."
  fi
elif [ "${OPENCODE_GO_OUTCOME}" != "success" ]; then
  need="true"
  echo "::notice title=mergecraft Codex fallback::OpenCode Go review failed; retrying with openai/gpt-codex."
fi
echo "need=${need}" >> "${GITHUB_OUTPUT}"
