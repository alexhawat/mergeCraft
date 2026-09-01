#!/usr/bin/env bash
# Shared mergecraft-approval / evidence-packet verdict helpers for cascade decide steps.

latest_mergecraft_approval() {
  local latest=""
  for attempt in $(seq 1 3); do
    if latest="$(gh api "/repos/${REPO}/commits/${HEAD_SHA}/check-runs" \
      --jq '[.check_runs[]? | select(.name == "mergecraft-approval")]
      | sort_by(.completed_at // .started_at) | last
      | "\(.id // "")|\(.conclusion // "")"')"; then
      break
    fi
    echo "check-runs query failed (attempt ${attempt}/3); retrying in 3s…" >&2
    sleep 3
  done
  printf '%s' "${latest}"
}

discard_baseline_verdict() {
  local latest="$1"
  local id="${latest%%|*}"
  local conclusion="${latest#*|}"
  if [ -n "${id}" ] && [ -n "${BASELINE_ID:-}" ] && [ "${id}" = "${BASELINE_ID}" ]; then
    echo "mergecraft-approval ${id} predates this attempt — treating as no verdict."
    conclusion=""
  fi
  printf '%s' "${conclusion}"
}

verdict_from_packet() {
  local packet="$1"
  if [ -n "${packet}" ]; then
    printf '%s' "$packet" | jq -r '.decision.verdict // empty' 2>/dev/null || true
  fi
}

# Codex fallback: only failure|success count as a posted verdict (neutral still falls back).
verdict_blocks_codex_fallback() {
  case "$1" in
    failure|success) return 0 ;;
    *) return 1 ;;
  esac
}

# Claude backstop: failure|success|neutral all count as a posted verdict.
verdict_blocks_claude_backstop() {
  case "$1" in
    failure|success|neutral) return 0 ;;
    *) return 1 ;;
  esac
}
