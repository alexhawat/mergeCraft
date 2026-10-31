#!/usr/bin/env bash
# Download mergecraft-coverage-json from a completed workflow run for COMMIT_SHA.
set -euo pipefail

usage() {
  echo "usage: $0 COMMIT_SHA OUTPUT_JSON_PATH" >&2
  exit 2
}

[[ $# -eq 2 ]] || usage

commit_sha="$1"
output_path="$2"

: "${GITHUB_REPOSITORY:?GITHUB_REPOSITORY is required}"
: "${GH_TOKEN:=${GITHUB_TOKEN:-}}"

if [[ -z "${GH_TOKEN}" ]]; then
  echo "ci_fetch_coverage_artifact: no GH_TOKEN/GITHUB_TOKEN — cannot download artifact" >&2
  exit 1
fi

repo="${GITHUB_REPOSITORY}"
artifact_name="mergecraft-coverage-json"

runs_json="$(gh api \
  "/repos/${repo}/actions/runs?head_sha=${commit_sha}&status=completed&per_page=20")"

run_ids="$(printf '%s' "${runs_json}" | jq -r '.workflow_runs[]? | .id')"

for run_id in ${run_ids}; do
  artifacts_json="$(gh api "/repos/${repo}/actions/runs/${run_id}/artifacts?per_page=100")"
  artifact_id="$(printf '%s' "${artifacts_json}" | jq -r \
    --arg name "${artifact_name}" \
    '[.artifacts[]? | select(.name == $name and .expired == false)] | first | .id // empty')"
  if [[ -z "${artifact_id}" ]]; then
    continue
  fi
  tmp_zip="$(mktemp)"
  cleanup() {
    rm -f "${tmp_zip}"
  }
  trap cleanup EXIT
  gh api "/repos/${repo}/actions/artifacts/${artifact_id}/zip" >"${tmp_zip}"
  extracted="$(unzip -Z1 "${tmp_zip}" | grep -E '(^|/)coverage\.json$' | head -n 1 || true)"
  if [[ -z "${extracted}" ]]; then
    echo "ci_fetch_coverage_artifact: artifact ${artifact_id} has no coverage.json" >&2
    continue
  fi
  unzip -p "${tmp_zip}" "${extracted}" >"${output_path}"
  echo "ci_fetch_coverage_artifact: reused mergecraft-coverage-json from run ${run_id} artifact ${artifact_id} for commit ${commit_sha}"
  exit 0
done

echo "ci_fetch_coverage_artifact: no ${artifact_name} artifact for ${commit_sha}" >&2
exit 1
