#!/usr/bin/env bash
# Resumable CI gate. Runs the ordered `make ci` steps (see `make ci-steps`), checkpointing
# each pass to .ci-progress, and STOPS at the first failing step (non-zero exit). On the next
# run it skips every already-passed step and resumes from the failed one — so an agent can fix
# one error and continue, without re-running the steps that already passed.
#
# When every step passes, the checkpoint is cleared and the run is equivalent to `make ci`
# (``CI_STEPS`` mirrors ``ci-static`` + ``security`` + ``coverage-gate`` only — advisory
# workflow jobs such as ``mutation-advisory`` are not included).
# Full ``make ci`` remains the authoritative gate; this is the iterative fix loop.
#
# NOTE (by design): after a fix, earlier steps are assumed still-passing and are NOT re-run.
# If a fix might break an earlier step, run `make ci-reset` (or this script with --reset) to
# start over, or finish with one clean `make ci`.
#
# Usage:
#   scripts/ci_resume.sh            # run/resume the gate
#   scripts/ci_resume.sh --reset    # clear the checkpoint and start over
#   scripts/ci_resume.sh --status   # show progress and exit
#
# Env:
#   MERGECRAFT_CI_PROGRESS_FILE   checkpoint path (default: <repo>/.ci-progress)
set -uo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$repo_root" || exit 2
STATE="${MERGECRAFT_CI_PROGRESS_FILE:-$repo_root/.ci-progress}"

case "${1:-}" in
  --reset)
    rm -f "$STATE"
    echo "ci-resume: checkpoint cleared ($STATE)"
    exit 0
    ;;
  --status)
    if [[ -s "$STATE" ]]; then
      echo "ci-resume: passed so far -> $(tr '\n' ' ' < "$STATE")"
    else
      echo "ci-resume: no checkpoint (fresh run)"
    fi
    exit 0
    ;;
  "") : ;;
  *)
    echo "ci-resume: unknown argument '${1}' (use --reset or --status)" >&2
    exit 2
    ;;
esac

steps="$(make -s ci-steps)"
if [[ -z "$steps" ]]; then
  echo "ci-resume: could not read step list (make ci-steps returned nothing)" >&2
  exit 2
fi

# total count (whitespace-separated)
# shellcheck disable=SC2086
set -- $steps
total=$#

[[ -f "$STATE" ]] || : > "$STATE"

i=0
for step in $steps; do
  i=$((i + 1))
  if grep -qxF "$step" "$STATE" 2>/dev/null; then
    echo "ci-resume [$i/$total] skip (already passed): $step"
    continue
  fi
  echo "ci-resume [$i/$total] running: make $step"
  if make "$step"; then
    echo "$step" >> "$STATE"
  else
    rc=$?
    echo ""
    echo "ci-resume: ❌ FAILED at '$step' (step $i/$total)."
    echo "  Fix the error, then re-run 'make ci-resume' — it will skip the $((i - 1)) passed"
    echo "  step(s) and resume from '$step'. To start over: 'make ci-reset'."
    exit "$rc"
  fi
done

rm -f "$STATE"
echo ""
echo "ci-resume: ✅ all $total steps passed (equivalent to 'make ci'; advisory CI jobs excluded)."
exit 0
