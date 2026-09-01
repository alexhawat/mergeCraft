#!/usr/bin/env bash
# Decide whether to fall back from Nous to Codex after a no-verdict Nous run.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=scripts/lib/provider_verdict_guard.sh
source "${ROOT}/scripts/lib/provider_verdict_guard.sh"

need="false"
if [ -n "${NOUS_PACKET:-}" ]; then
  verdict="$(verdict_from_packet "${NOUS_PACKET}")"
  if verdict_blocks_codex_fallback "${verdict}"; then
    echo "packet decision.verdict=${verdict} — Nous review posted a verdict; not falling back to Codex."
  else
    need="true"
    echo "::notice title=mergecraft Codex fallback::Nous review posted no verdict in evidence packet (action outcome: ${NOUS_OUTCOME}); retrying with openai/gpt-codex."
  fi
elif [ "${EVENT_NAME}" = "pull_request_target" ]; then
  latest="$(latest_mergecraft_approval)"
  conclusion="$(discard_baseline_verdict "${latest}")"
  if verdict_blocks_codex_fallback "${conclusion}"; then
    echo "mergecraft-approval=${conclusion} — Nous review posted a verdict; not falling back to Codex."
  else
    need="true"
    echo "::notice title=mergecraft Codex fallback::Nous review posted no verdict (action outcome: ${NOUS_OUTCOME}); retrying with openai/gpt-codex."
  fi
elif [ "${NOUS_OUTCOME}" != "success" ]; then
  need="true"
  echo "::notice title=mergecraft Codex fallback::Nous review failed; retrying with openai/gpt-codex."
fi
echo "need=${need}" >> "${GITHUB_OUTPUT}"
