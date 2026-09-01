# mergeCraft PR review — hardened reference workflow.
#
# Auto-reviews PRs on open / ready / new commits, posting inline comments plus a
# summary, and (with `status_checks: enabled`) the `mergecraft` and
# `mergecraft-approval` check-runs. The final step fails the job when
# `mergecraft-approval` concluded "would not approve", so a branch ruleset can
# require this job and block merges with outstanding review feedback.
#
# It ALWAYS fails open when the review cannot run — fork PR without secrets,
# provider session limit, no approval posted. A required check that can go
# permanently missing is a permanent merge block, which is worse than no gate.
#
# ---------------------------------------------------------------------------
# Trigger choice: pull_request_target vs pull_request
# ---------------------------------------------------------------------------
# This template uses `pull_request_target`. GitHub SKIPS `pull_request` workflows
# when `refs/pull/N/merge` cannot be built — i.e. whenever the PR has a merge
# conflict — so a required review check sits unreported for as long as the
# conflict lasts. `pull_request_target` still fires on `synchronize` in that
# state, so the review lands while the PR is still conflicted.
#
# Do not over-read that. Pushing the conflict fix to the PR branch fires
# `synchronize` and clears a `pull_request` check too, so the gap is the
# conflicted window, not a permanent block; it outlasts the conflict only when
# the conflict disappears WITHOUT a push to the head branch (the base moved),
# because nothing then re-triggers the run. A conflicted PR is unmergeable on
# its own account anyway. Weigh this against running with secrets in scope.
#
# The cost is that `pull_request_target` runs with repository secrets in scope, so
# it MUST NOT execute PR-authored code. This workflow does not: the same-repo
# guard below withholds secrets from fork PRs, and mergeCraft runs with
# `push: disabled` / `shell: disabled` and reaches PR content through its own
# `checkout_pr` + API layer.
#
# If your review job is NOT a required check, plain `pull_request` is simpler and
# safer — use it.
#
# ---------------------------------------------------------------------------
# WHERE THIS FILE MUST LIVE
# ---------------------------------------------------------------------------
# Under GitHub's Nov 2025 policy (effective 2025-12-08), `pull_request_target`
# definitions are resolved from the repository's DEFAULT BRANCH — not from the
# PR's base branch. Consequences:
#
#   * The default-branch copy runs for every PR, whatever base it targets.
#   * A PR that edits this file cannot review itself with its own changes; they
#     take effect on the next PR after merge.
#   * If your trunk is NOT the default branch (e.g. `main` is a stub and real
#     work lands on a staging branch), keep this file ONLY on the default branch.
#     A second copy on the trunk is inert, has to be hand-mirrored forever, and
#     invites the two copies to drift.
#
# If you also pin the action SHA somewhere else — a Makefile variable for local
# review runs, a devcontainer, docs — gate the two against each other in CI, and
# read the workflow side from the DEFAULT BRANCH (`git show origin/main:<path>`),
# not from the working tree. Comparing a working-tree copy that never executes
# against your Makefile checks two values that do not matter while the pin that
# actually runs goes unverified. Bump order is then: default branch first, local
# pin second — the gate compares against the default branch, so the reverse order
# fails.
# ---------------------------------------------------------------------------

name: mergeCraft

on:
  # NOTE: no `issue_comment` / `pull_request_review_comment` triggers here, by
  # design. This job runs under `pull_request_target` with repository secrets in
  # scope, and a comment trigger would let any commenter hand the agent a prompt
  # inside that context (issue #72 / D6). mergeCraft refuses comment-driven
  # invocation under `pull_request_target` at runtime regardless — the
  # `allow_pr_target_comments: 'true'` input exists only for workflows whose
  # `if:` condition already restricts comment triggers to trusted authors. Use
  # `workflow_dispatch` below for on-demand runs.
  pull_request_target:
    # Add every base branch that should be auto-reviewed. Globs work:
    # branches: [main, develop, "release-*"]
    branches: __BASE_BRANCHES__
    types: [opened, synchronize, reopened, ready_for_review]
  workflow_dispatch:
    inputs:
      prompt:
        description: Prompt for the agent (workflow_dispatch only)
        required: false
        type: string

permissions:
  contents: read
  # Download SARIF artifacts uploaded by the consumer CI workflow (ciEvidence ingest).
  actions: read
  # Post the inline PR review + comments.
  pull-requests: write
  issues: write
  # Post the mergecraft / mergecraft-approval check-runs.
  checks: write
  statuses: write
  # Uncomment TOGETHER WITH `sarif_upload: enabled` below to publish analyzer
  # findings as code-scanning alerts (#39). Left off here so copying this
  # template changes nothing until you decide to opt in; without the permission
  # GitHub answers 403 and mergeCraft logs a warning rather than failing.
  # security-events: write
  # Only needed if mergeCraft mints short-lived tokens via OIDC.
  id-token: write

concurrency:
  # pull_request_target resolves github.ref to the default branch, so keying on
  # github.ref would collapse every open PR into one group and they would cancel
  # each other. Key on the PR number.
  group: mergecraft-${{ github.workflow }}-${{ github.event.pull_request.number || github.ref }}
  cancel-in-progress: true

jobs:
  # Hold the review until your own CI has finished on the PR head SHA, so the
  # reviewer reads real lint/type/test outcomes instead of speculating about them.
  # `needs:` cannot reference another workflow file, so this polls the check-runs
  # API for the jobs named by CI_JOB_PREFIX.
  #
  # Delete this job (and the `needs:` below) if you do not want reviews to wait.
  #
  # ALWAYS fails open (`exit 0` on every path): if the review job is required, a
  # wait that could fail would turn a slow or absent CI run into a permanent merge
  # block. Timing out just means the review proceeds without CI context.
  wait-for-ci:
    name: mergeCraft wait for CI
    if: github.event_name == 'workflow_dispatch' || github.event.pull_request.draft == false
    runs-on: ubuntu-latest
    timeout-minutes: 25
    outputs:
      # complete | timeout | absent | skipped
      state: ${{ steps.wait.outputs.state || 'skipped' }}
      failed_count: ${{ steps.wait.outputs.failed_count || '0' }}
      failed_names: ${{ steps.wait.outputs.failed_names || '' }}
      check_suite_id: ${{ steps.wait.outputs.check_suite_id || '' }}
    steps:
      - name: Wait for CI checks on the PR head SHA
        id: wait
        if: github.event_name == 'pull_request_target'
        env:
          GH_TOKEN: ${{ github.token }}
          REPO: ${{ github.repository }}
          HEAD_SHA: ${{ github.event.pull_request.head.sha }}
          # Name prefix of YOUR CI jobs. Set this to whatever your CI workflow
          # calls its jobs, e.g. "build (" or "test (".
          CI_JOB_PREFIX: __CI_JOB_PREFIX__
          # Total budget. Set a little above your CI's usual wall time; keep it
          # below this job's timeout-minutes.
          WAIT_BUDGET_SECONDS: "1200"
          # If no matching job has appeared by then, assume CI is not running for
          # this PR and stop waiting.
          APPEAR_BUDGET_SECONDS: "300"
        run: |
          set -uo pipefail
          jq_verify="[.check_runs[]? | select(.name | startswith(\"${CI_JOB_PREFIX}\"))]"
          started="$(date +%s)"
          state="timeout"
          failed_count=0
          failed_names=""
          check_suite_id=""

          while :; do
            now="$(date +%s)"
            elapsed=$(( now - started ))

            if runs="$(gh api --paginate "/repos/${REPO}/commits/${HEAD_SHA}/check-runs?per_page=100" 2>/dev/null | jq -s '{check_runs: [.[].check_runs[]?]}')" ; then
              total="$(printf '%s' "${runs}" | jq "${jq_verify} | length")"
              pending="$(printf '%s' "${runs}" | jq "${jq_verify} | map(select(.status != \"completed\")) | length")"

              if [ "${total}" -gt 0 ] && [ "${pending}" -eq 0 ]; then
                state="complete"
                failed_count="$(printf '%s' "${runs}" | jq "${jq_verify} | map(select(.conclusion != \"success\" and .conclusion != \"neutral\" and .conclusion != \"skipped\")) | length")"
                failed_names="$(printf '%s' "${runs}" | jq -r "${jq_verify} | map(select(.conclusion != \"success\" and .conclusion != \"neutral\" and .conclusion != \"skipped\") | .name) | join(\", \")")"
                # Any failing job carries the check_suite id the reviewer needs
                # for get_check_suite_logs().
                check_suite_id="$(printf '%s' "${runs}" | jq -r "${jq_verify} | map(select(.conclusion != \"success\" and .conclusion != \"neutral\" and .conclusion != \"skipped\") | .check_suite.id) | first // \"\"")"
                break
              fi

              if [ "${total}" -eq 0 ] && [ "${elapsed}" -ge "${APPEAR_BUDGET_SECONDS}" ]; then
                state="absent"
                break
              fi
            else
              echo "check-runs query failed (elapsed ${elapsed}s) — retrying" >&2
            fi

            if [ "${elapsed}" -ge "${WAIT_BUDGET_SECONDS}" ]; then
              state="timeout"
              break
            fi
            sleep 10
          done

          {
            echo "state=${state}"
            echo "failed_count=${failed_count}"
            echo "failed_names=${failed_names}"
            echo "check_suite_id=${check_suite_id}"
          } >> "${GITHUB_OUTPUT}"
          echo "CI wait finished: state=${state} failed=${failed_count} suite=${check_suite_id:-none}"
          case "${state}" in
            timeout) echo "::notice title=mergeCraft CI wait::CI did not finish within ${WAIT_BUDGET_SECONDS}s — reviewing without CI context." ;;
            absent)  echo "::notice title=mergeCraft CI wait::No matching CI checks appeared for ${HEAD_SHA} — reviewing without CI context." ;;
          esac
          exit 0

  review:
    name: mergeCraft review
    needs: wait-for-ci
    # `always()` keeps the required check reporting even if the (fail-open) wait
    # job errors out on a runner fault; a skipped wait job still skips the review,
    # because the draft/dispatch condition below is the same one it uses.
    if: >-
      always() &&
      (github.event_name == 'workflow_dispatch' || github.event.pull_request.draft == false)
    runs-on: ubuntu-latest
    timeout-minutes: 30
    env:
      # Same-repo guard: fork PRs must never receive repository secrets under
      # pull_request_target.
      IS_SAME_REPO: ${{ github.event_name == 'workflow_dispatch' || github.event.pull_request.head.repo.full_name == github.repository }}
      # #37 / W4 — the review step walks the configured chain, so any
      # credential in the chain qualifies as "we can run". The Claude pair is
      # listed first because the hardened template pins ``model: anthropic/
      # claude-sonnet`` as the chain head; uncomment the other provider env
      # vars below to extend the chain (and the gate) — the single
      # ``uses:`` step walks them in the order `.mergecraft/config.yaml`
      # declares under ``models:``.
      HAS_AUTH: ${{ (secrets.CLAUDE_CODE_OAUTH_TOKEN != '' || secrets.ANTHROPIC_API_KEY != '' || secrets.OPENAI_API_KEY != '' || secrets.CODEX_AUTH_JSON != '' || secrets.GEMINI_API_KEY != '') && (github.event_name == 'workflow_dispatch' || github.event.pull_request.head.repo.full_name == github.repository) }}

    steps:
      # No `ref:` here, deliberately. Under pull_request_target this checks out
      # the DEFAULT BRANCH — trusted code — and mergeCraft reaches PR content
      # through its own `checkout_pr` + API layer instead. Do not "fix" this by
      # adding `ref: ${{ github.event.pull_request.head.sha }}`,
      # `refs/pull/N/merge`, or `repository: <head repo>`: that is the classic
      # pwn-request, and since actions/checkout v7 (GA 2026-06-18, backported to
      # all supported majors 2026-07-20) it hard-fails on fork PRs unless you
      # pass `allow-unsafe-pr-checkout`. If you find yourself reaching for that
      # flag under pull_request_target, switch to `pull_request` instead.
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
          # MUST stay false. actions/checkout persists its token as an
          # `extraheader = AUTHORIZATION: basic ...` entry in .git/config, and the
          # mergeCraft action adds its own `Authorization` header. git treats
          # `extraHeader` as multi-valued, so both land on one request and GitHub
          # answers 400 "Duplicate header: Authorization" — checkout_pr fails and
          # the review never reaches a verdict. The action authenticates from its
          # own `token:` input and needs nothing persisted here.
          persist-credentials: false

      - name: Ensure PR base ref exists locally
        if: github.event_name == 'pull_request_target'
        run: |
          set -euo pipefail
          base="${{ github.event.pull_request.base.ref }}"
          git fetch --no-tags origin "${base}:refs/remotes/origin/${base}"
          # pull_request_target checks out the DEFAULT branch. When the PR targets
          # that same branch, `git branch -f` fails because it is the active
          # worktree — and origin/<base> is already fetched above.
          if [ "$(git rev-parse --abbrev-ref HEAD)" != "${base}" ]; then
            git branch -f "${base}" "origin/${base}"
          fi

      - name: Skip when provider auth is not configured
        if: env.HAS_AUTH != 'true'
        run: |
          if [ "${{ env.IS_SAME_REPO }}" != "true" ]; then
            echo "::notice title=mergeCraft skipped::Fork PR — secrets are withheld, review skipped."
          else
            echo "::notice title=mergeCraft skipped::Set a credential for at least one provider in the chain (CLAUDE_CODE_OAUTH_TOKEN / ANTHROPIC_API_KEY / OPENAI_API_KEY / CODEX_AUTH_JSON / GEMINI_API_KEY) to enable reviews."
          fi

      # Composed in a step rather than inline in `with:` so the CI-context clause
      # stays readable. Every interpolated value is repo-controlled (PR number,
      # base ref, our own wait-job outputs) — no PR-authored free text reaches the
      # prompt.
      - name: Compose review prompt
        id: prompt
        if: env.HAS_AUTH == 'true'
        env:
          PR_NUMBER: ${{ github.event.pull_request.number }}
          BASE_REF: ${{ github.event.pull_request.base.ref }}
          EVENT_NAME: ${{ github.event_name }}
          DISPATCH_PROMPT: ${{ inputs.prompt }}
          CI_STATE: ${{ needs.wait-for-ci.outputs.state }}
          CI_FAILED_COUNT: ${{ needs.wait-for-ci.outputs.failed_count }}
          CI_FAILED_NAMES: ${{ needs.wait-for-ci.outputs.failed_names }}
          CI_CHECK_SUITE_ID: ${{ needs.wait-for-ci.outputs.check_suite_id }}
        run: |
          set -euo pipefail
          if [ "${EVENT_NAME}" != "pull_request_target" ]; then
            text="${DISPATCH_PROMPT:-Review the current pull request.}"
          else
            text="Review pull request #${PR_NUMBER}. First call the mergecraft MCP tool mergecraft_checkout_pr (the checkout_pr tool on the mergecraft MCP server — already configured). Do NOT install, request, or wait for any GitHub plugin. For base-side file reads use origin/${BASE_REF}:path, not bare branch names. If prior mergeCraft threads are resolved and the latest commits address them, submit approved:true with a short summary. Focus on correctness, security, regressions, missing tests, and maintainability. Leave concise, actionable comments only for issues that should be addressed before merge."
            # The action runs with `shell: disabled`, so the reviewer cannot run
            # lint/typecheck/tests itself. Hand it the CI outcome instead — and the
            # check_suite id, because no MCP tool can discover one.
            case "${CI_STATE}" in
              complete)
                if [ "${CI_FAILED_COUNT}" -gt 0 ] 2>/dev/null; then
                  if [ -n "${CI_CHECK_SUITE_ID}" ]; then
                    text="${text} CI has finished on this head commit and ${CI_FAILED_COUNT} job(s) FAILED (${CI_FAILED_NAMES}). Call mergecraft_get_check_suite_logs with check_suite_id ${CI_CHECK_SUITE_ID} and ground your review in those failures — report the underlying defect, not the log line."
                  else
                    text="${text} CI has finished on this head commit and ${CI_FAILED_COUNT} job(s) FAILED (${CI_FAILED_NAMES}). get_check_suite_logs is unavailable (check_suite id unknown); still treat these mechanical failures as blocking and note the limitation."
                  fi
                else
                  text="${text} CI has finished green on this head commit, so lint, typecheck, and the full test suite already pass; do not speculate about mechanical failures those gates would have caught, and spend the review on logic, design, and missing coverage."
                fi
                ;;
              *)
                text="${text} CI results are NOT available for this head commit (wait state: ${CI_STATE}), so no lint/typecheck/test signal informs this review. Do not assert that the change passes or fails those gates."
                ;;
            esac
          fi
          {
            echo "text<<MERGECRAFT_PROMPT_EOF"
            echo "${text}"
            echo "MERGECRAFT_PROMPT_EOF"
          } >> "${GITHUB_OUTPUT}"

      - name: mergeCraft PR review
        if: env.HAS_AUTH == 'true'
        id: mergecraft
        continue-on-error: true
        # Pin to a full-length commit SHA. Many orgs enforce Actions SHA pinning,
        # which rejects a branch ref at action-resolution time — before the step
        # runs. Keep this SHA equal to any other place you pin mergeCraft.
        uses: __ACTION_REPO__@__ACTION_PIN__
        with:
          prompt: ${{ steps.prompt.outputs.text }}
          # Must stay BELOW the job's timeout-minutes: when GitHub kills the job
          # first, the action never posts its `mergecraft` completion check and
          # the only diagnostic is lost. 5 minutes of headroom lets it exit
          # cleanly and report failure instead.
          timeout: 25m
          # #37 / W4 — a single `uses:` step walks the configured chain. The
          # ``model:`` input is the chain head; the configured ``models:``
          # list (in `.mergecraft/config.yaml`) is the tail. Uncredentialed
          # providers are skipped with a warning; retryable failures advance.
          # Set ``model_pin: enabled`` ONLY if you want to suppress the
          # fallback (rare). See `examples/config.yaml` for the chain config.
          model: anthropic/claude-sonnet
          # model_pin: enabled   # uncomment to suppress fallbacks (legacy semantics)
          push: disabled
          shell: disabled
          status_checks: enabled
          # Trust-aware analyzer selection (#38). `auto` already resolves to this
          # under `pull_request_target`, but stating it keeps the workflow honest
          # about what it expects and survives any future change to `auto`.
          # Only analyzers needing no secrets, no network and no PR-authored
          # command construction run; the rest are skipped with a named reason in
          # the Analyzers pre-merge row, never reported as failures.
          analyzers: untrusted-only
          # Optional (#39): publish the analyzer findings above as GitHub
          # code-scanning alerts, so mechanical signal stays readable when the
          # review narrative is thin or findings overflow the inline comment
          # budget. Off by default. Uncomment this AND `security-events: write`
          # in the `permissions:` block. Only findings from analyzers this run's
          # trust tier admitted are uploaded, after secret redaction; CI log
          # excerpts and agent narrative are never uploaded, and a rejected
          # upload is logged rather than failing the review.
          # sarif_upload: enabled
        env:
          CLAUDE_CODE_OAUTH_TOKEN: ${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }}
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          # Add a second provider's credentials here to extend the chain —
          # the single ``uses:`` step above walks them in order. See the
          # Custom OpenAI-compatible provider section in README.md and the
          # multi-provider worked example for the env-var convention.
          # OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
          # CODEX_AUTH_JSON: ${{ secrets.CODEX_AUTH_JSON }}
          # GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}

      - name: mergeCraft review incomplete (non-fatal)
        if: env.HAS_AUTH == 'true' && steps.mergecraft.outcome != 'success'
        run: |
          echo "::notice title=mergeCraft incomplete::Review step did not finish successfully (see its log). Approval enforcement skipped."

      # Gate on the approval check-run rather than on the review step's exit code,
      # so agent infrastructure failures do not read as "changes requested".
      #
      # W8.4 (D13): the approval conclusion is computed structurally from the
      # typed `Finding` list + run state + trust tier — narrative ("approved",
      # "not approved") never enters the decision. The hardened enforce step
      # treats anything other than `success` as blocking:
      #
      # - `failure` ⇒ review surfaced a blocker (Critical/Major finding) — block.
      # - `neutral` ⇒ the run crashed / timed out / produced no findings, or
      #   the trust tier is `untrusted` (fork PR / pull_request_target) — block.
      #   `neutral` is the wire-shape that means "no permissive gate"; an
      #   injected PR that suppresses its findings still surfaces `neutral`
      #   because the structural decision reads the typed finding list.
      # - `success` ⇒ review completed, no blockers, at least one finding — pass.
      # - absent (no `mergecraft-approval` check posted at all, e.g. the
      #   review step never ran) ⇒ still fail open. The required check
      #   pattern relies on a posted check; if no check exists, the GitHub
      #   branch-protection rule itself blocks the merge, not this step.
      - name: Fail when mergeCraft would not approve
        if: github.event_name == 'pull_request_target' && env.HAS_AUTH == 'true'
        env:
          GH_TOKEN: ${{ github.token }}
          REPO: ${{ github.repository }}
          HEAD_SHA: ${{ github.event.pull_request.head.sha }}
        run: |
          set -euo pipefail
          conclusion=""; queried=""
          for attempt in $(seq 1 5); do
            if conclusion="$(gh api "/repos/${REPO}/commits/${HEAD_SHA}/check-runs" \
                --jq '[.check_runs[]? | select(.name == "mergecraft-approval")]
                      | sort_by(.completed_at // .started_at) | last | .conclusion // ""')"; then
              queried="yes"; break
            fi
            echo "check-runs query failed (attempt ${attempt}/5); retrying in 5s…" >&2
            sleep 5
          done
          if [ -z "${queried}" ]; then
            echo "::warning title=mergeCraft approval unknown::Could not query check-runs for ${HEAD_SHA} after retries. Failing open."
            exit 0
          fi
          case "${conclusion}" in
            success)
              echo "mergeCraft approval: structural gate passed (no blockers in the typed Finding list)."
              ;;
            failure)
              echo "::error title=mergeCraft requested changes::mergecraft-approval failed — the typed Finding list contains a Critical or Major finding."
              exit 1
              ;;
            neutral)
              echo "::error title=mergeCraft review incomplete::mergecraft-approval is 'neutral' — the run crashed, timed out, produced no findings, or ran on an untrusted tier. This is treated as blocking by W8 (D13)."
              exit 1
              ;;
            *)
              echo "::notice title=mergeCraft approval not posted::No mergecraft-approval check on ${HEAD_SHA}. Not blocking (fail-open for missing check — branch protection handles the missing required check)."
              ;;
          esac
