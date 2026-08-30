# Simplifying `mergecraft.yml` — moving bash out of consumer YAML

**Status:** proposal / discussion
**Scope:** `.github/workflows/mergecraft.yml`, `scripts/example_workflows/hardened.yml.tpl`,
`action.yml`, `src/mergecraft/`
**Goal:** reduce what an operator must write, read, and maintain to run mergeCraft
reviews in their own repo.

---

## 1. Where the complexity actually is

Measured on the current `main` copy of `.github/workflows/mergecraft.yml`:

| Metric | Lines |
| --- | ---: |
| Total file | 1049 |
| Comment-only lines | 499 |
| Blank lines | 31 |
| Actual YAML | 519 |
| **Inline bash inside `run:` blocks** | **277** |

The inline bash breaks down as:

| Step | File line | Bash lines |
| --- | ---: | ---: |
| Wait for CI checks on the PR head SHA | 196 | 55 |
| Decide Codex fallback after Nous | 641 | 48 |
| Decide Claude backstop after the provider cascade | 798 | 43 |
| Fail when mergeCraft would not approve | 980 | 43 |
| Compose review prompt | 419 | 35 |
| Resolve PR for workflow_dispatch | 386 | 21 |
| Record mergecraft-approval baseline | 466 | 14 |
| Ensure PR base ref exists locally | 362 | 10 |
| Skip when provider auth is not configured | 377 | 6 |
| mergeCraft review incomplete (non-fatal) | 931 | 2 |

The operator-facing template (`scripts/example_workflows/hardened.yml.tpl`) is
**433 lines carrying ~130 lines of the same bash**. That is the number to attack:
none of it is repo-specific. It is all mergeCraft protocol plumbing leaking into
consumer YAML, where the operator has to understand it and keep it in sync with
our verdict semantics forever.

### The duplication

The same "query the latest `mergecraft-approval` check-run, with a 3-attempt
retry loop" appears **four times**:

- `Record mergecraft-approval baseline` (line 466)
- `Decide Codex fallback after Nous` (line 641)
- `Decide Claude backstop after the provider cascade` (line 798)
- `Fail when mergeCraft would not approve` (line 980, 5 attempts instead of 3)

The two decider blocks are ~80% identical — same query, same baseline-id
comparison, same `jq` verdict extraction — differing only in which condition
triggers them (verdict absence vs. retryable step failure).

The `HAS_AUTH` expression is duplicated verbatim across the `review` and
`approval-gate` jobs, guarded by a test (`tests/ci/test_approval_gate_auth_predicate.py`)
because it has already drifted once in production.

---

## 2. Suggestions, ordered by leverage

### S1 — Ship a reusable workflow (`on: workflow_call`)

**Impact: operator file 433 → ~15 lines.**

Publish `.github/workflows/mergecraft-review.yml` in this repo with a
`workflow_call` trigger. The operator's entire workflow becomes:

```yaml
name: mergecraft
on:
  pull_request_target:
    branches: [main]
    types: [opened, synchronize, reopened, ready_for_review]
permissions:
  contents: read
jobs:
  review:
    uses: alexhawat/mergeCraft/.github/workflows/mergecraft-review.yml@v1
    secrets: inherit
    with:
      ci-job-prefix: "Verify ("
      providers: "nous,codex,claude"
```

The bash still exists, but **we** own it and version it. An operator never reads
it, and a fix ships to every consumer with a tag bump instead of N hand-mirrored
copy-pastes across N repos.

Precedent: `e2e.yml` in this repo already uses `workflow_call`.

**Caveats to design for:**

- Pin the called workflow to a tag or SHA, same discipline as the action pin.
  `pull_request_target` + reusable workflow resolves the *caller* from the
  default branch; the callee resolves from the ref you pin.
- `secrets: inherit` passes everything. Prefer an explicit `secrets:` block so
  the credential manifest stays legible and auditable
  (`src/mergecraft/workflow/auth_manifest.py` already models this).
- Reusable workflows cannot be nested more than 4 deep and cannot use
  `strategy: matrix` on the calling job in some configurations — neither
  constrains this use.

---

### S2 — Promote verdict state to action **outputs** (deletes code, not moves it)

**Impact: removes ~105 lines of YAML and an entire class of race condition.**

The two decider blocks and the baseline snapshot exist *only* because the action
does not tell the workflow what happened. `action.yml` already emits `result`,
`evidence_packet`, and `verdict_diagnostic`. Add two more:

```yaml
outputs:
  verdict:
    description: >
      Terminal verdict this attempt posted: "success", "failure", or "" when the
      attempt reached no terminal verdict.
  failure_class:
    description: >
      "" when the attempt ran to completion; "retryable" for a quota ceiling,
      timeout, or transport death; "fatal" for a non-recoverable error.
```

Both deciders then collapse to plain step conditions:

```yaml
- name: mergeCraft PR review (Codex)
  if: env.HAS_CODEX == 'true' &&
      (env.HAS_NOUS != 'true' || steps.mergecraft_nous.outputs.verdict == '')

- name: mergeCraft PR review (Claude)
  if: env.HAS_CLAUDE == 'true' &&
      (steps.mergecraft_nous.outputs.failure_class == 'retryable' ||
       steps.mergecraft_codex.outputs.failure_class == 'retryable') &&
      steps.mergecraft_codex.outputs.verdict == ''
```

This deletes:

- `Decide Codex fallback after Nous` (48 lines)
- `Decide Claude backstop after the provider cascade` (43 lines)
- `Record mergecraft-approval baseline` (14 lines)

**Why the baseline goes away entirely.** The baseline-check-run-id snapshot
exists to answer "did *this* attempt post a verdict, or am I reading a stale one
from a previous run on the same head SHA?" That question is only hard from
*outside* the action. The action knows what it posted. Asking it directly
removes the need to infer freshness by comparing check-run ids against a
pre-run snapshot — and removes the failure mode where an empty `BASELINE_ID`
makes a stale verdict look fresh (a bug the current comments already document).

**Note the different routing rules are preserved, not lost.** Codex routes on
`verdict == ''` (Nous can exit 0 while posting nothing usable — the MCP
handshake symptom). Claude routes on `failure_class == 'retryable'` (a provider
that could not run at all). The distinction survives as two different output
fields instead of two near-identical shell scripts.

---

### S3 — `mergecraft ci wait` — move CI polling into the product

**Impact: 55 lines of bash → one CLI call, and it becomes unit-testable.**

`src/mergecraft/ci/` already exists with `verification.py`, `evidence.py`,
`normalize.py`, and a `providers/` registry. A check-run wait belongs there.

```bash
mergecraft ci wait \
  --head-sha "$HEAD_SHA" \
  --name-prefix "Verify (" \
  --budget-seconds 1200 \
  --appear-budget-seconds 300 \
  --github-output
```

Emits `state` / `failed_count` / `failed_names` / `check_suite_id` to
`$GITHUB_OUTPUT` and always exits 0 (fail-open is a property of the command, not
of a `exit 0` an operator might delete by accident).

**Real trade-off, decide it deliberately:** today's bash runs on the bare runner
using preinstalled `gh` — zero startup cost. A Python entrypoint means pulling
the Docker image or a `pip install`, adding roughly 30–60s. Given the job already
budgets 20 minutes of waiting, that is noise. But it is a genuine cost and
should be an explicit choice, not a side effect.

**Upside beyond line count:** the polling loop, the appear-budget semantics, and
the "which conclusions count as failure" predicate become testable in pytest
instead of only in production.

---

### S4 — `mergecraft gha gate` — move the approval gate into the product

**Impact: 43 lines → one call, and fail-closed becomes a tested invariant.**

```bash
mergecraft gha gate --head-sha "$HEAD_SHA" --check-name mergecraft-approval
```

Exit 0 only on `conclusion=success`; exit non-zero on `failure`, on no check
posted, and on an unreachable check-runs API after retries. That is exactly the
current semantics — but expressed once, in a place where
`tests/` can assert every branch, rather than in shell where the only proof is a
long comment explaining why each path fails closed.

The `gha` Typer app already exists (`src/mergecraft/cli/gha_cmd.py`) with
`$GITHUB_OUTPUT` / `$GITHUB_STATE` helpers, so this is a natural sibling to the
existing `gha token` subcommand.

---

### S5 — Composite actions for whatever must stay shell

**Impact: bash moves from YAML strings into real `.sh` files.**

If S1/S3/S4 are too large a step, this is the cheap version:

```
.github/actions/mergecraft-wait-for-ci/
    action.yml
    wait.sh
.github/actions/mergecraft-approval-gate/
    action.yml
    gate.sh
```

Consumers reference them as
`uses: alexhawat/mergeCraft/.github/actions/mergecraft-wait-for-ci@<sha>`.

Benefits:

- Real `.sh` files get `shellcheck` in CI (you already run `scripts/workflow_lint.sh`).
- Testable with `bats` or a plain harness.
- Syntax highlighting and editor tooling actually work.
- Each workflow step becomes one line.

---

### S6 — Functions: `scripts/gha/lib.sh`

**Impact: kills the 4× duplicated check-runs query.**

If some logic stays in bash, factor the repeated parts:

```bash
# scripts/gha/lib.sh

# Echoes "id|conclusion" for the newest check-run with the given name on a SHA.
# Retries a transient API failure. Returns non-zero if every attempt failed.
latest_check_run() {  # $1=repo $2=sha $3=name $4=attempts
  ...
}

# Echoes the terminal verdict from an evidence packet, or "" when absent.
verdict_from_packet() {  # stdin=packet JSON
  jq -r '.decision.verdict // empty'
}

# True when $1 (an id) is set and differs from $2 (the baseline id).
is_fresh_verdict() {  # $1=id $2=baseline_id
  ...
}
```

Each `run:` block starts with `source "${GITHUB_WORKSPACE}/scripts/gha/lib.sh"`.

**Honest assessment:** this is the weakest option. It helps *our* copy, but a
consumer of the action still owns the same bash in their repo — `source` needs
the file checked out, which the operator's workflow may not do. Treat S6 as a
stopgap for logic that genuinely cannot move into S1–S4, not as the destination.

---

### S7 — Remove the `HAS_AUTH` duplication

The `review` and `approval-gate` jobs hold character-for-character identical
`HAS_AUTH` expressions, and
`tests/ci/test_approval_gate_auth_predicate.py` exists specifically to catch the
drift that already happened once (Claude was added to one copy and not the
other, failing the gate **open** on a Claude-only repo).

Options, best first:

1. Under S1 it is computed once in the reusable workflow. Problem disappears.
2. Short of that, emit it as a job output and read
   `needs.review.outputs.has_auth` in the gate.
3. Failing both, keep the test — but treat it as debt, not a solution.

---

### S8 — Move the postmortem comments to `docs/`

499 of 1049 lines are comment-only. Roughly 400 of those are historical
narrative: nine action-SHA bump postmortems (lines ~501–584 alone are ~80 lines
on a single step), PR-number archaeology, and "lesson for whoever bumps this
next."

That history is genuinely valuable — it is why the pins are where they are. It
is just not reference material for someone reading control flow.

Proposal: `docs/workflow-history.md`, with a one-line pointer in the YAML:

```yaml
# Action pin history and provider-cascade postmortems: docs/workflow-history.md
MERGECRAFT_ACTION_SHA: "fcb64c11d839d8ff4cf18bb925362080873df067"
```

Keep in the YAML only the comments that explain a *non-obvious current
invariant* — e.g. why `persist-credentials: false` is mandatory, why the two
deciders route on opposite signals, why the gate fails closed. Those are load-
bearing. The bump chronology is not.

---

## 3. Recommended sequence

| Order | Change | Removes | Risk |
| --- | --- | --- | --- |
| 1 | **S2** — `verdict` + `failure_class` outputs | ~105 lines | Low. Additive to `action.yml`; old workflows keep working. |
| 2 | **S8** — history to `docs/` | ~400 comment lines | None. |
| 3 | **S1** — reusable workflow | operator's 433 → ~15 | Medium. Needs a tag/pin story and a secrets decision. |
| 4 | **S3 + S4** — `ci wait`, `gha gate` | ~98 lines | Medium. Adds image-pull latency; needs the fail-open/closed invariants ported carefully. |
| 5 | **S7** — de-duplicate `HAS_AUTH` | 1 expression, 1 test | Low, once S1 lands. |
| 6 | **S5 / S6** — composites, shell lib | remainder | Low. Only for what S1–S4 leave behind. |

**If only two things happen: S2 and S1.**

S2 first, because it is the only suggestion that *deletes* logic rather than
relocating it — the deciders and the baseline stop being necessary rather than
moving somewhere tidier. S1 second, because it is the one the operator actually
feels.

Together they take the operator-facing file from 433 lines to roughly 15, and
this repo's own workflow from 1049 lines to roughly 200.

---

## 4. What should stay complicated

Not everything here is accidental. These are load-bearing and should survive any
cleanup:

- **The three-provider cascade.** A deliberate response to real provider
  unreliability. Simplify its *expression* (S2), not its behavior.
- **Fail-closed approval gating.** A required check that fails open is worse
  than no check. Every non-success path exiting 1 is correct.
- **`pull_request_target` + the same-repo secret guard.** The security model
  depends on it, and PR #200 documents what happens when it is relaxed.
- **Full-SHA action pins.** Non-negotiable; enforced by `make action-pin-check`.
- **`persist-credentials: false`.** Removing it reintroduces the duplicate
  `Authorization` header failure.

The goal is fewer lines expressing the same guarantees — not fewer guarantees.
