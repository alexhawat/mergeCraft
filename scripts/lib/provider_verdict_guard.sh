#!/usr/bin/env bash
# Shared mergecraft-approval / evidence-packet verdict helpers for cascade decide steps.

# Newest ``mergecraft-approval`` check-run attributable to this run: same head,
# this run's ``<run id>:<attempt>`` external id, and an issuer this repository
# trusts (github-actions, or the App named by EXPECTED_APP_ID when set). Prints
# ``<id>|<conclusion>``; prints ``|`` when no such check exists, so a foreign or
# stale check is never read as a verdict. Callers prefer the rung's own packet
# verdict and reach this only when no packet was produced, which keeps routing
# on the same set the approval gate judges.
latest_mergecraft_approval() {
  local expected_external="${GITHUB_RUN_ID:-}:${GITHUB_RUN_ATTEMPT:-}"
  local json="" attempt=""
  for attempt in $(seq 1 3); do
    if json="$(gh api "/repos/${REPO}/commits/${HEAD_SHA}/check-runs?check_name=mergecraft-approval&filter=all&per_page=100")"; then
      break
    fi
    echo "check-runs query failed (attempt ${attempt}/3); retrying in 3s…" >&2
    sleep 3
  done
  printf '%s' "${json}" | jq -r --arg head "${HEAD_SHA}" \
    --arg ext "${expected_external}" --arg app "${EXPECTED_APP_ID:-}" '
      [ .check_runs[]?
        | select(.name == "mergecraft-approval")
        | select(.head_sha == $head)
        | select(.external_id == $ext)
        | select((.app.slug // "") == "github-actions"
                 or ($app != "" and ((.app.id // 0) | tostring) == $app))
      ]
      | sort_by(.completed_at // .started_at)
      | last
      | "\(.id // "")|\(.conclusion // "")"
    ' 2>/dev/null || true
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
