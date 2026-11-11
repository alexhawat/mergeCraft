#!/usr/bin/env bash
# Download mergecraft-coverage-json from a completed workflow run for COMMIT_SHA.
# MERGECRAFT_COVERAGE_ARTIFACT_EVENT (optional) restricts the runs considered to one
# trigger event: the base lookup passes ``push`` so a fork's pull_request run for the
# same SHA can never supply the baseline; the head lookup passes ``pull_request``.
# MERGECRAFT_COVERAGE_ARTIFACT_STATUS=any also considers runs that are still in
# progress: the head lookup uses it so Integration reads the artifact as soon as the
# coverage gate uploads it, not when every other CI job has finished.
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

event_filter=""
if [[ -n "${MERGECRAFT_COVERAGE_ARTIFACT_EVENT:-}" ]]; then
  event_filter="&event=${MERGECRAFT_COVERAGE_ARTIFACT_EVENT}"
fi

status_filter="&status=completed"
if [[ "${MERGECRAFT_COVERAGE_ARTIFACT_STATUS:-}" == "any" ]]; then
  status_filter=""
fi

runs_json="$(gh api \
  "/repos/${repo}/actions/runs?head_sha=${commit_sha}&per_page=20${status_filter}${event_filter}")"

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

# Exit 3 is a definitive miss: no publishing run is still going, so waiting longer
# cannot produce the artifact. Exit 1 means a publishing run is still in progress and
# callers may poll.
# Only runs of a workflow that uploads the artifact count, and never the run that is
# executing this script: the Integration run polling here is itself in progress, so
# counting it would make "nothing can still publish" unreachable.
# shellcheck disable=SC2016
publishers='[.workflow_runs[]? | select((.path // "" | test("^\\.github/workflows/(ci|ci-cd)\\.yml")) and ((.id | tostring) != $self))]'
unfinished="$(printf '%s' "${runs_json}" | jq --arg self "${GITHUB_RUN_ID:-}" "${publishers} | map(select(.status != \"completed\")) | length")"
echo "ci_fetch_coverage_artifact: no ${artifact_name} artifact for ${commit_sha}" >&2
# No publisher run in progress (none listed, or all finished without the artifact):
# nothing can still produce it.
if [[ "${unfinished}" -eq 0 ]]; then
  exit 3
fi
exit 1
