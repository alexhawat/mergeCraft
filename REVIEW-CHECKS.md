# What mergecraft checks for

> **Doc status (W7 + catalog C6):** §2 describes the analyzer platform and the expanded
> P0–P3 catalog. Long-tail tools default to **disabled** unless repo config or detection
> enables them.

Every check mergecraft applies when it reviews a pull request, grouped by what it is looking at.

A quick orientation before the lists:

- Most of these are **judgment checks** carried out by the reviewing agent, not scripted rules. There is no rule engine — the behavior lives in the `Review` and `IncrementalReview` mode prompts in [`src/mergecraft/modes/Review.py`](src/mergecraft/modes/Review.py) and [`src/mergecraft/modes/IncrementalReview.py`](src/mergecraft/modes/IncrementalReview.py).
- **Mechanical evidence** comes from two layers: your repo's own gates (`staticChecks` / Makefile targets via `run_static_checks`) and mergeCraft's **catalog analyzers** (`run_analyzers`). Only **`failed`** gate status and **verified** analyzer findings become review signal — everything else is reported as skipped.
- Groups 1–3 are the ones that produce findings. Groups 4–8 govern how findings are graded, placed, filtered, and formatted — they are why the review stays short.

## Contents

1. [Code correctness and risk](#1-code-correctness-and-risk) — the review lenses
2. [Analyzers](#2-analyzers) — catalog tools + repo gates
3. [Pull request hygiene](#3-pull-request-hygiene) — the pre-merge checks table
4. [Diff coverage](#4-diff-coverage)
5. [Finding grading](#5-finding-grading)
6. [Findings that get dropped](#6-findings-that-get-dropped)
7. [Memory across runs](#7-memory-across-runs)
8. [Output shape](#8-output-shape)
9. [Address-reviews checks](#9-address-reviews-checks)
10. [Trajectory checks](#10-trajectory-checks-43-49)
11. [Deterministic run record](#11-deterministic-run-record-plan-12)

---

## Mechanical evidence — what counts (#41, W2.5)

Mechanical evidence is what the merge-evidence packet calls **structural**
— typed `Finding`s, deterministic gate outcomes, and CI check-suite
results. It is the *only* category of evidence that can move the merge
verdict; everything else is advisory. Concretely:

- **Typed `Finding`s** — emitted by the analyzer catalog (`Finding` from
  `mergecraft.analyzers.finding`, `extra="forbid"`). Each finding carries
  `tool`, `rule_id`, `category`, `severity`, `confidence`, `path`,
  `start_line`/`end_line`, `fingerprint`, `evidence: list[str]`,
  `introduced_by_pr`, `source`, `scope`, `cluster_id`. Findings are the
  authoritative structural input to `decide_approval()`. Only `scope="change"`
  findings can block; `scope="run"` rows are advisory and partition into the
  packet's `run_health` section at assembly time (plan 12).
- **`DeterministicCheck` rows** — one per declared `staticChecks` or
  discovered Makefile target. Status is one of five: `passed`, `failed`,
  `timed_out`, `unavailable`, `declared-but-cannot-run`. **Only
  `failed`** is a negative finding; **only `passed`** is a positive
  signal. The other three are honest skips, never silent passes.
- **CI check-runs** — raw `check_suite` data from `mcp/check_runs.py`
  plus the cluster/blame/flaky annotations from `src/mergecraft/ci/`.
- **The agent's `approved` boolean** — **NOT** mechanical evidence. It
  is recorded on the packet as `self_assessment` and is advisory only;
  a self-assessment-only run cannot reach `auto_merge` (the #41 hard
  rule, pinned by `tests/evidence/test_self_assessment.py`).

What does *not* count as mechanical evidence, even when it appears in a
check-run summary or in the agent's prose:

- The agent's review narrative — `ApprovalRecord.would_approve`,
  `result.output`, anything the model wrote.
- PR title / body / comment text (even when fenced and unfenced by
  trust tier) — see the `Trust tiers and contributor weight` section in
  `docs/REVIEW-DOCTRINE.md`.
- A "green" status with no underlying typed finding — `unavailable` /
  `declared-but-cannot-run` / `timed_out` are explicit and visible; the
  absence of evidence is itself evidence the verdict must surface.

The merge-evidence packet's `decision` row is computed by
`mergecraft.agents.gates.decide_approval(findings, *, run_succeeded,
tier)` from these structural inputs. When the packet is given directly
to `decide_approval(packet, …)`, the explicit `Decision` row on the
packet wins over every other signal — including the recorded
`self_assessment`.

## Terminal verdict vs structural verdict (VP2)

A review run is not complete until the agent records a **terminal
submission** through `submit_review_verdict`. Provider success, review
prose, and `create_pull_request_review` publication are separate acts:

- **Agent verdict** — the model's `approve` / `request_changes` choice,
  summary, and structured findings submitted through the typed MCP tool.
  This is the only signal that answers "did a review happen on this
  attempt?"
- **Structural verdict** — what `decide_approval` computes from typed
  findings, `run_succeeded`, and trust tier. Narrative output and
  `ApprovalRecord.would_approve` are advisory only and never override a
  confirmed blocker.

**Schema vs semantic validation.** The tool rejects unknown fields and
invalid verdict enums at parse time. After schema validation,
`validate_submission` applies semantic rules server-side: `request_changes`
with zero findings, `approve` over a verifier-confirmed Critical/Major
blocker, and `approve` while a required deterministic gate failed are all
rejected with a typed `rejection_reason`. A rejected submission does not
set `terminal_submission_received` — the attempt is fallback-eligible and
maps to `RunOutcome.inconclusive`, same as no submission at all.

**Why prose is not authoritative.** Text such as "LGTM" in `result.output`
has never been an input to `decide_approval` and cannot approve a pull
request. A run whose provider returned successfully but never called
`submit_review_verdict` now reports `inconclusive` (`neutral` check
conclusion) instead of `passed`.

**Fallback interaction.** Semantic fallback advances when
`terminal_submission_received` is false — whether because no submission
was recorded or because the validator rejected one. A valid
`request_changes` verdict with confirmed findings is a usable result and
does not trigger fallback.

## 1. Code correctness and risk

The reviewer reads the whole diff itself, then picks the **lenses** the PR actually warrants and investigates each as a falsifiable question — optionally dispatching a `mergecraft-reviewer` subagent per lens so they run in parallel. Nothing here is a fixed pass; a docs-only diff gets none of it.

Each review round records which lenses were **selected**, which were **skipped** (with reasons from deterministic routing), and which were **actually dispatched**. That set is written into the review metadata HTML comment and the merge-evidence packet so the next round — and incremental complement routing in a follow-up review — can read what already ran without re-deriving it from prose.

**Run lifecycle (S1)** — a failed or timed-out trusted-tier `setupScript` yields `RunOutcome.inconclusive` (neutral check conclusion), not a review. An under-provisioned tree never receives a review verdict. See [`docs/config-failure-policy.md`](docs/config-failure-policy.md#setup-script-failures-s1--d5--d10--f6) for the policy table and operator checklist.

**Always in play**

- **Correctness and invariants** — bugs, races, error handling, edge cases, state-machine boundaries.
- **Data integrity and atomicity** — for any diff that writes persistent state: is the write ordered after the thing it records is confirmed, or before? does failing halfway leave a half-committed state with no rollback? is a retry idempotent, or does it double-apply?
- **Impact** — stale references left in code, tests, docs, configs, or UI after a rename or removal.
- **Copy vs code** — does every human-readable string still match what the code does? Help text, menu labels, error messages, `--help` output, README and doc claims, and the PR description's own promises.
- **Holistic** — does the PR make sense as a whole? Symmetric flows: a delete for every create, a rollback for every migration.

**Picked when the diff warrants it**

- **Security** — new endpoints, authorization, input validation, secret handling, replay / CSRF / injection, cross-tenant isolation.
- **Privilege drop ordering** — for a diff where a privileged process (root, before a `setpriv`/`sudo -u`/`su`/container-user-switch step) creates a file or directory that a later, lower-privileged process must then read or write: does the write land only after ownership is fixed for the dropped-privilege user, or does the privileged process's plain `mkdir()`/file write leave the path owned by the wrong uid? Ownership follows the *creating* process, not the parent directory's owner and not a later chmod/chown applied only to the parent — this is how mergeCraft shipped `Permission denied` bugs against its own `$HOME` and `$CODEX_HOME`/`.gemini`/`.claude` writes twice in production.
- **Performance** — N+1 queries, hot-path allocation, latency budgets, index coverage.
- **Test integrity** — meaningful coverage for the changed behavior, deterministic, no shared-state pollution.
- **User journey** — for UX-touching flows, walking the happy path and the failure modes as a user.
- **Operational readiness** — observability, alerting, forward and rollback migrations, feature flags, on-call burden.
- **Integration and cross-cutting** — API contracts between modules, backward compatibility of public surfaces, multi-service ordering.
- **Research-validated assumptions** — third-party API contracts, SDK semantics, framework directives, version-gated behavior. Only when the PR's correctness *depends* on the contract behaving a certain way, and the reviewer must cite source URLs.
- **Subsystem lenses** — invented per PR for high-stakes domains: auth, billing, payments, schema migration, webhooks, secrets, RBAC, multi-tenant isolation, cron/scheduling. Preferred over the generic equivalent, because "the billing lens" primes for double-charges and refund races in a way "correctness on billing code" does not.

**Non-anchored concerns** — deliberately hunted for after the line-anchored findings, since these have no line to point at:

- Deletion or cleanup plans for code the diff replaces or shadows.
- Rollout sequencing — what happens to in-flight state during deploy or revert.
- Coverage gaps the diff implies but does not add.
- Scope questions only a human can answer (is the legacy path going away, or is this a long-term dual track?).
- Architectural risks the diff opens up that are not a single-line bug.

## 2. Analyzers

Deterministic evidence from catalog tools and your repo's own gates. The reviewer calls `run_analyzers` (catalog) and `run_static_checks` (repo gates) early in Review / IncrementalReview — results feed the **Analyzers** and **Mechanical gates** pre-merge rows and may become inline findings.

### Repo mechanical gates (`run_static_checks`)

Your repo's own gate — unchanged from prior mergeCraft behavior:

- **Declared gates** — `staticChecks` in `.mergecraft/config.yaml`. `{files}` expands to changed paths; `suffixes` skips when no matching file changed.
- **Discovered gates** — with nothing declared, mergecraft looks for `lint`, `format-check`, `typecheck`, and `ci-static` Makefile targets. Skipped when `make` is not installed.
- **Nothing found** → skipped. mergecraft will **not** substitute a linter of its own (`except A, B:` is legal on Python 3.14 and a syntax error on 3.13 — version mismatch manufactures false positives).

Each gate returns one of six statuses; only **`failed`** is a finding:

| Status | Meaning |
|---|---|
| `passed` | ran, exit 0 |
| `failed` | ran, non-zero exit — a finding |
| `timed_out` | exceeded the per-gate timeout |
| `unavailable` | executable not installed — judged nothing |
| `declared-but-cannot-run` | gate is declared in config but this environment cannot execute it (for example `shell: disabled` on a pull-request event) — judged nothing, but the gate is visible instead of silently omitted |
| `satisfied-by-ci` | the gate did not run here, but a check run your repo **declared** as proof of it passed on this commit — green, with the check run named |

When `staticChecks` are configured but every gate is `unavailable` or `declared-but-cannot-run`, `run_static_checks` returns `ran: false` with an explicit reason and one row per configured gate so the **Mechanical gates** pre-merge row can report skipped instead of implying the repo has no gates.

#### Reusing your CI as gate evidence (`ciEvidence`, #36)

The Action image usually has no `make`, no repo venv, and none of your pinned toolchains — so a gate reports `unavailable` even when your own CI just proved it on the same commit. Declare the mapping and that finished CI stands in:

```yaml
ciEvidence:
  gates:
    lint: Verify (drift gates)   # <gate name>: <exact GitHub check-run name>
```

- **Declared only.** A check run merely *named* like a gate proves nothing — a pull request can add a workflow with any name it likes. With no `ciEvidence` block mergeCraft never reads your check runs at all.
- **Only green substitutes.** A declared check run that passed rewrites that gate's row to `satisfied-by-ci`, replacing the `unavailable` row rather than adding a second one. A declared check run that **failed** leaves the honest row in place and is reported as a CI finding — the report never claims a green gate on red evidence.
- **A gate that actually ran here always wins.** CI cannot overwrite a verdict mergeCraft produced against this diff.
- **Best effort.** No head SHA, no declared mapping, or a GitHub API error → the gate report is exactly what it would have been without the feature.

### Catalog analyzers (`run_analyzers`)

Shipped catalog spans **P0 workflow/Docker gates** (actionlint, zizmor, ShellCheck, Hadolint),
**repo-native language gates** (Ruff, type checkers, ESLint/Biome/Oxlint), **supply chain**
(OSV-Scanner, Trivy, TruffleHog), **pattern scanners** (Semgrep/OpenGrep, ast-grep),
**differential contracts** (oasdiff, Squawk, buf breaking), **agent security** (native YAML
rules on MCP/skill manifests), and **P1–P3 long-tail manifests** (Go, Rust, IaC, SQL, PHP,
Ruby, …) — each is YAML plus an existing parser, not bespoke adapter code.

Reference: [`docs/ANALYZERS.md`](docs/ANALYZERS.md) (generated from manifests; CI-enforced).
Contributor path: [`docs/CONTRIBUTING-ANALYZERS.md`](docs/CONTRIBUTING-ANALYZERS.md).
Offline inspection: `mergecraft analyzers list|detect|run|explain|export --sarif|lock`.

**Execution preference (D4):** `repo-native` → existing CI result → managed pinned binary → container → **skip with a named reason**. Skipped is skipped — never a finding, never a failed pre-merge row.

**Trust tiers (D7):** `trusted` (same-repo PR, `workflow_dispatch`, offline `diff-review`) vs `untrusted` (fork PR / `pull_request_target` — no secrets, network deny-by-default, no PR-authored command construction; trusted-only manifests skip with reasons). Offline `diff-review` runs analyzers at trusted tier without shell.

**`shell: disabled` (#35):** hardening the workflow no longer costs you the catalog. Repo-declared gates stay withheld — they run command strings the PR author controls — but mergeCraft's own **`managed` / `container` analyzers still run**, because their argv comes verbatim from a manifest mergeCraft ships and a repo-provided binary may not stand in for the pinned one. `repo-native` manifests are withheld, each with a named reason, since they exist to run the repo's own tool against the repo's own config. What a consumer sees on a `pull_request_target` + `shell: disabled` run: analyzer rows for the managed tools that matched the diff, `unavailable` rows naming why each other manifest was withheld, and the `staticChecks` gates reported as `declared-but-cannot-run`. The full runtime × shell × trust matrix is generated into [`docs/ANALYZERS.md`](docs/ANALYZERS.md).

**Scoping (D6):** analyzers run on **head** by default; findings outside the diff hunks are dropped unless the path is an explicit exception (new file, dependency manifest, lockfile, workflow, migration). `introduced_by_pr: unknown` when no base run happened — never implied `true`.

**Clustering (D12):** one defect from multiple tools publishes **one** finding with corroborating evidence and raised `confidence`.

**Verification (D11):** Critical/Major analyzer hits are **hypotheses** until the read-only `mergecraft-verifier` subagent confirms, downgrades, or drops them. Drops write a reason under `## Withdrawn review findings (known non-issues)`.

**Noise budget (D14):** inline analyzer slots cap at **8** (W0.2 measurement). Analyzer overflow lands in `### 🔧 Mechanical findings` (compact tool table). Agent overflow lands in `### 🗂 Deferred findings` with full finding text (non-blocking, server-appended). Agent findings win ties; Trivial/Low value never inline.

**Lockfile (D24):** `.mergecraft/analyzers.lock` records resolved tool id, version, source, and SHA256; the pre-merge **Analyzers** row echoes the digest.

### CI pipeline intelligence (`analyze_ci_failures`)

When CI failed on the PR head, mergeCraft calls `analyze_ci_failures`, which wraps `get_check_suite_logs` and normalizes failures behind `GitHubActionsProvider`.

To discover a `check_suite_id` for a commit, call `list_check_runs` with the PR head SHA (or `get_check_suite` when you already have an id). Then pass that id to `get_check_suite_logs` or `analyze_ci_failures`.

**What is read**

- Failed workflow job/step names, exit codes, and redacted log excerpts
- Retry attempt history and base-branch run fingerprints (when available)
- PR diff paths for blame overlap

**What is inferred**

- Root-cause clustering by failure fingerprint (twelve shards from one broken import → one finding)
- Flaky vs stable vs pre-existing classification from retry flips and base-branch evidence
- PR attribution (`caused_by_pr` vs `probably_not_this_pr`) from diff overlap — never asserted without evidence
- Truncation when more failures exist than the configured cap (default 3)

**What is explicitly not claimed**

- mergeCraft does not re-run CI, retry jobs, or push fix commits
- Non-GitHub providers (CircleCI, GitLab, Azure) are honestly stubbed — no silent empty results
- A failure outside the diff is **reported, not blamed** on the author
- Flaky failures are named flaky rather than treated as the author's defect

The review publishes `### 🚨 CI failures` with clustered root causes, flaky/blame verdicts, and redacted excerpts. The pre-merge **CI** row reports failure count, cluster count, flaky count, PR-attributed count, and whether truncation occurred. Inline CI comments may carry a one-click `suggestion` when the fix is a contained single-hunk edit; pushing a fix commit stays behind the existing `push` permission.

**Recorded as evidence (#36).** Each clustered CI failure is also recorded as a `source: ci` finding on the run and carried into the [merge evidence packet](docs/REVIEW-DOCTRINE.md), keeping the blame verdict it was given: a failure attributed to this PR is `Major` / `introduced_by_pr: true`, while a flaky or pre-existing one is `Minor` / `introduced_by_pr: false`. Since every gate that consumes findings is monotone in blockers, that annotation is what makes "reported, not blamed" mechanical rather than a matter of wording — a flaky pipeline cannot block a clean pull request.

**SARIF your CI already produced.** Naming artifacts under `ciEvidence.sarifArtifacts` lets the reviewer ingest their SARIF as CI findings through the same parser the analyzer catalog uses. Default is empty, in which case no artifact API call is made. Ingested results are reported at a non-blocking severity with `introduced_by_pr: unknown` — SARIF from another pipeline describes the tree, not this diff.

Implementation: [`src/mergecraft/ci/intelligence.py`](src/mergecraft/ci/intelligence.py), [`src/mergecraft/ci/review.py`](src/mergecraft/ci/review.py), [`src/mergecraft/ci/cluster.py`](src/mergecraft/ci/cluster.py), [`src/mergecraft/mcp/ci_intelligence.py`](src/mergecraft/mcp/ci_intelligence.py), [`src/mergecraft/mcp/check_suite.py`](src/mergecraft/mcp/check_suite.py), [`src/mergecraft/mcp/check_runs.py`](src/mergecraft/mcp/check_runs.py).

## 3. Pull request hygiene

Assertions about the pull request itself rather than its code. These always appear, as a small **Pre-merge checks** table at the top of the review body:

- **Title** — does it name the main change? Flagged when it covers only part of the diff, or names something the diff doesn't do.
- **Description** — does it explain what changed and why, and does every claim in it hold against the diff?
- **Linked issues** — for each issue the PR closes, is every stated requirement actually covered?
- **Scope** — does the diff do things neither the description nor a linked issue asked for? Out-of-scope paths get named.
- **Mechanical gates** — the result from `run_static_checks` (repo gates).
- **Analyzers** — the result from `run_analyzers` (catalog tools): how many ran, how many skipped (with reasons), lockfile digest.
- **CI** — pipeline intelligence on failing check suites: failure count, cluster count, flaky count, PR-attributed count, and whether truncation occurred. Flaky or probably-not-this-PR failures are reported here, not blamed on the author.

A flagged row here is fixed by editing the PR's title, body, or issue links — not its code — so these never also become inline comments. The one exception is a failing mechanical gate, which is a real code finding and is raised inline too.

## 4. Diff coverage

Checks on the review process itself, so a review can't quietly skip half the PR:

- The complete raw diff is read end-to-end, using the diff's table of contents as a coverage checklist.
- On a re-review, an incremental patch covering only the commits since mergeCraft's last review scopes what is new — the full diff still establishes coverage.
- A first submission that missed regions gets a one-time nudge listing the unread ranges.
- Understanding is never delegated: subagents supply lens investigations, but the primary reviewer synthesizes and re-verifies every finding.
- **Trivially skippable** — a single-word doc typo, whitespace-only changes, comment-only changes, lockfile or generated-code regeneration, a mechanical rename, a low-risk dependency patch bump.
- **Looks trivial but is not** (small diff, big blast radius — never skipped):
  - any one-line change to SQL, regex, auth, billing, permission, or signature-verification code
  - flipping a feature-flag default, a default config value, or a retry/timeout constant
  - changing a money, tax, currency, or fee constant by any amount
  - changing an HTTP method, redirect URL, response code, or status enum
  - tightening or loosening a comparison operator (`<` ↔ `<=`, `==` ↔ `!=`)
  - renaming a public API surface
  - adding a new direct dependency
  - a "typo fix" in user-facing copy that changes meaning ("approved" → "denied")
  - a semantic one-liner buried in a formatting-only diff

### Blast-radius merge lanes

The packet's blast-radius classification is an evidence-weighted policy signal,
not an instruction to merge. `low` means the change is eligible for the
auto-merge lane after required checks pass, `medium` means assisted review, and
`high` means automatic merge is forbidden. These semantics do not enable or
disable auto-merge; `autoMergeEnabled` remains `false`, and Batch D (#46) owns
the separate mapping from evidence outcomes to workflow actions.

## 5. Finding grading

Every surviving finding is graded on three independent axes before it is placed. The grade decides placement, so it isn't decoration.

- **Category** — picked by where the *consequence* lands, not what the code looks like: Functional Correctness · Data Integrity & Atomicity · Security & Privacy · Stability & Availability · Performance & Scalability · Maintainability & Code Quality.
- **Severity** — Critical (blocks merge) · Major (real fallout if shipped) · Minor (worth fixing, ships fine without) · Trivial (nit).
- **Effort** — Quick win (contained, obvious) · Heavy lift (needs design, spans files, or has migration implications) · Low value (correct, not worth the churn).

Then placement is mechanical:

- `Trivial` **or** `Low value` → a bullet in the body's Nitpicks list, never an inline comment.
- everything else → an inline comment at its line, tagged `_{category}_ | _{severity}_ | _{effort}_`, **unless** it overflowed the inline budget as an agent finding — then it lands in the non-blocking `### 🗂 Deferred findings` section (server-appended, full text, no inline anchor).

**Collateral (RC11):** every `Critical` or `Major` finding names what else must move with the fix — callers, tests, docstrings, configs, or other files — in the finding's `collateral` list and in the inline comment body under an **Also update:** bullet list. Collateral is not required for `Minor` or `Trivial` findings. Any collateral claim about code the diff doesn't contain must ship with evidence; without evidence it is downgraded to a question or dropped (§6).

The axes are also a sweep: a PR that writes persistent state with no Data Integrity & Atomicity finding gets one more look before the reviewer concludes there was nothing there.

Values live in [`src/mergecraft/review_taxonomy.py`](src/mergecraft/review_taxonomy.py); a test asserts the prompt still names every one of them.

### Verification before publication

Every `Critical` / `Major` finding is a hypothesis until a second, read-only agent
(`mergecraft-verifier`) has read the cited code. That applied to analyzer and CI findings from
the start; it now applies to the findings the reviewing agent wrote itself, which is the source
most likely to be wrong.

Before publishing, the reviewer hands its own `Critical` / `Major` findings to
`verify_agent_findings`, which returns one dispatch brief per finding — the finding, its cited
file, and the withdrawn-findings section. Three things bound the cost:

- **Severity** — `Minor` and `Trivial` findings are never verified.
- **Memory** — a finding whose fingerprint already appears under `## Withdrawn review findings` is
  skipped outright, not re-verified.
- **Budget** — dispatches are capped at the repo's `review.verificationBudget` (default 24; `0` =
  no cap), spent on `Critical` before `Major`. Verification depth is independent of inline
  placement (`analyzers.inlineBudget`, default 8). Over-budget fingerprints are recorded in
  `skippedOverBudget` rather than silently dropped.

Each verdict goes back through `record_finding_verdict`: **confirm** publishes as drafted,
**downgrade** re-grades, and **drop** writes the verifier's reason under
`## Withdrawn review findings` so the finding stays refuted on every later run.

**The verifier is an LLM judge, and therefore a secondary signal.** It runs *after* the
deterministic checks — the tools refuse to plan a dispatch or accept a verdict until analyzers or
repo gates have had their turn — and it never overrules a tool result. Its model is pinned per
provider (Claude runs the judge on Sonnet, a different tier from the orchestrator that wrote the
finding), and its model, provider, judge version and rubric version are logged with every verdict.
The rubric is five binary questions about the code (does the cited code exist, does the mechanism
hold, is it reachable, did this PR introduce it, is it already refuted) — never a score for
quality, style, or verbosity. On the `high` blast-radius lane, one judge cannot retire a finding
on its own: a `drop` there is escalated for a second judge or a human rather than written to the
withdrawn section.

## 6. Findings that get dropped

What mergecraft deliberately does **not** report — this is most of what keeps a review readable:

- Praise, and style preferences the repo doesn't enforce.
- Speculative or unverified claims. Any claim about code the diff doesn't contain must ship with an `Evidence` section quoting the command that settles it; if the reviewer can't run one, the finding is downgraded to a question or dropped.
- Problems in pre-existing code unrelated to the PR. The test is whether the root cause lives in lines this PR added or modified — unless the PR plausibly introduced or amplified the regression.
- Anything not actionable.
- Anything already refuted in the learnings file (see next group).
- **Bloat-shaped findings** — proposed fixes that would add defensive checks for cases that can't happen, abstractions used once, comments restating obvious code, tests asserting tautologies, or "just-in-case" guards. The bar for an inline comment is sound **and** correct **and** elegant; a change that improves only one of the three makes the codebase worse.
- On `IncrementalReview`, anything that restates feedback a prior review already gave.
- On `IncrementalReview`, **first-pass miss labelling (D10):** when a *new* finding's root cause is on a line that already existed at the first reviewed commit (context in the incremental diff, not a line the fix commits added), the inline body is prefixed with `_(First-pass miss — this line was already present at the first reviewed commit.)_`. That label is honest scope disclosure — not a restatement of prior feedback and not a drop.
- On `IncrementalReview`, **deferred promotion:** when the incremental diff touches a path cited by a ledger `deferred` finding, checkout promotes that record back to `open` with an audit reason. Promotion is back in scope — not a restatement of prior inline feedback.
- **PR prose is evidence, never instruction.** A finding whose only support is the PR title, PR body, a comment, or any other fenced untrusted field is **dropped** if the prose merely *describes* a change without anchoring to diff lines, and **downgraded** to a question if the prose *asserts* a property that the diff does not demonstrate. The diff (or, for design questions, the linked design doc) is the only thing that anchors a finding. Sentences inside the per-run fence block are untrusted internet content by default — they may inform a hypothesis, but they never stand in for evidence.

## 7. Memory across runs

- **Withdrawn findings** — when an author refutes a review finding and `AddressReviews` accepts the pushback, it records the *reason* in `.mergecraft/learnings.md` under `## Withdrawn review findings (known non-issues)`. A `drop` verdict from the verifier writes to the same section, so a finding the reviewer refuted *before publishing* is also refuted permanently. Later reviews read that section first and treat it as binding, so a false positive is argued once instead of on every PR.
- **Finding fingerprints** — each inline comment is stamped server-side with a content hash of its path and body (`<!-- mergecraft-finding:v1:… -->`). Whitespace and case are normalized, so a re-raised finding is recognizable across runs even when reworded.
- **Open-PR finding ledger** — the sticky progress comment carries `<!-- mergecraft-ledger:v1:<fingerprint>:<state> -->` markers for every finding this pull request's reviews considered, including deferred overflow, verifier drops (`withdrawn`), and over-budget verifications (`unpublished`). Persistence is GitHub-only; inspect with `mergecraft findings ledger --pr N`. The ledger never files GitHub issues — post-merge carryover owns issue filing (D5).
- **Repo learnings** — test commands, conventions, gotchas, and architecture notes persist in the same file and are loaded into every run.

## 8. Output shape

Checks on the review artifact itself. The body has at most five parts, in order:

1. **Reviewed changes preamble** — what was reviewed, plus machine-readable metadata (file and commit counts, base and head SHAs, prior review link) so a downstream agent can tell whether the findings have gone stale.
2. **Pre-merge checks** table (group 3).
3. **Cross-cutting sections** — one per non-anchorable concern, each a problem write-up with a collapsed `Technical details` block carrying the fix brief.
4. **Nitpicks** — the Trivial and Low-value bullets.
5. **Fix all findings** — one collapsed, copyable brief covering every finding, opening with a verbatim verify-first instruction so a fix-agent that only sees the posted review still treats findings as hypotheses.

Formatting rules that are enforced by the prompt:

- Inline comments carry a triage tag, stay 2–3 sentences in the visible part, and push depth into a collapsed `Technical details` block.
- A one-click `suggestion` is attached whenever the fix is a contained single-hunk edit — and omitted when the reviewer can't produce exact replacement text, since a suggestion that doesn't apply cleanly is worse than none.
- Problem statements describe the problem; asks and fixes live in the technical-details block.
- Severity emoji on every section heading, no two consecutive prose paragraphs, backticks around every identifier, no repeated diff content, no line-count stats.
- The opening callout tier (`[!CAUTION]`, `[!IMPORTANT]`, informational, or ✅) must match the author's actual next action — wrapping mergeable feedback in `[!IMPORTANT]` trains people to ignore it.
- **Multi-reviewer provenance (`raised_by`).** When more than one reviewer binding
  runs, each finding may carry a `_Raised by: \`reviewer-id\`_` line in the
  published body. The field is **server-stamped at merge time** from the dispatch
  pairing `(reviewer_id, findings)` — it is **not** on the agent-facing
  `submit_review_verdict` schema (`additionalProperties: False`; an agent-supplied
  `raised_by` is rejected). Unknown provenance reads `unknown`, never the primary
  reviewer. `raised_by` is display and record only: it does not affect verdict,
  severity, dedup identity (`finding_key` stays `(path, body, line)`), or inline
  placement.

## 10. Trajectory checks (#43, #49)

Everything above reads the **diff**. These eight checks read *how the run
produced it* — the tool calls mergeCraft mediated. A diff can look clean while
the process that produced it was not, and that is invisible to a diff review.

| Check | Fires when | Severity |
|---|---|---|
| `changed-unread-file` | A file was modified that the run never read | Major |
| `ignored-tool-error` | A tool call errored and that tool was never called again | Major |
| `no-post-edit-verification` | Files were modified and nothing verifying ran *afterwards* | Major |
| `repeated-tool-loop` | The same call, with identical arguments, three or more times | Minor |
| `unresolved-failure` | A command reported failure and no later run of it passed | Critical |
| `suspicious-broad-edit` | One run modified 25+ files | Minor |
| `stale-assumption-after-failure` | A failed call was retried byte-identically with nothing read in between | Major |
| `missing-completion-signal` | The run did work and never signalled completion | Minor |

Each finding carries the severity above and a recommended action.

**Silence on absent evidence.** mergeCraft only sees the calls it mediates, so a
driver whose file reads never cross MCP produces a record with no reads — which
is *unknown*, not *unread*. Every check that could fire on missing signal is
gated on the record carrying that signal at all: `changed-unread-file` needs
`read_coverage`, `missing-completion-signal` needs at least one recorded call. A
check that fires on every run is noise, not a gate.

**Run-scoped, never blocking (D2).** Trajectory checks stamp `scope="run"`,
`source="trajectory"`, and `introduced_by_pr="false"`. They partition into the
packet's `run_health` section and render under a separate collapsed heading in
the deterministic run record. `blocking_findings()` drops them before severity
grading — no severity, and no future check, makes a run-scoped finding fail a
PR. There is no separate trajectory verdict and no second required check-run
(D14).

**They never crowd out code findings.** Inline slots go to code findings first;
trajectory findings take only what is left and otherwise report in the body or
the run-health section.

## 11. Deterministic run record (plan 12)

Every run that resolves a PR number leaves exactly one authoritative sticky
progress comment, whether the agent published a review, posted no verdict, or
failed mid-run (D6). Re-runs edit the same comment in place via the existing
sticky marker — they do not append a second one.

The comment and the published review body both render from
`render_deterministic_review_block()` in `findings/ledger.py` (D7), so the two
surfaces cannot drift. The agent cannot suppress the block by supplying its own
copy of the markers — dedupe keeps the server's version.

The block always contains, in order:

1. **Run header** — outcome, verdict diagnostic, decision verdict and reason,
   model actually used, attempt count, token summary, run URL, reviewed SHA,
   publication path, and whether 422 recovery demoted inline comments into the body.
2. **Pre-merge checks** — analyzers (dispatched lenses or packet summary),
   static checks from `deterministic_checks`, CI intelligence pointer, trust
   tier.
3. **Change-scoped findings** — typed packet rows (`scope="change"`); `_No
   change-scoped findings recorded._` when empty.
4. **Run health** — collapsed `<details>` with `scope="run"` findings when
   present; omitted when none.
5. **Agent summary or rejection** — when a verdict exists, the agent's summary
   quoted beneath the deterministic rows; when it does not, an explicit
   `No verdict recorded — reason: <typed rejection>` line.

The same block is merged into the review body as a mandatory preamble through
`merge_deterministic_preamble_into_review_body` in `mcp/review.py`, applied
last so nothing can be appended above it.

**Token summary band.** The **Tokens** row reports `used (target N, ceiling M)`,
optionally `over target` when spend crossed `runBounds.tokenBudget` but remains
below the ceiling, and `by phase: …` when call sites annotated `record_tokens(…,
phase=…)`. `tokenBudget` is the soft target; `tokenBudgetTolerance` (default
`0.10`) defines the hard ceiling as `target × (1 + tolerance)`. Tolerance `0`
restores strict enforcement at the target.

**`raised_by` on the record.** Terminal-submission finding rows and the
published review body carry `raised_by` for multi-reviewer attribution (see §8).
The merge-evidence packet's typed `Finding` model does **not** include
`raised_by` — provenance lives on the terminal layer and the deterministic run
record, not in packet `findings[]`.

## 9. Address-reviews checks

When mergecraft is on the receiving end of review comments (`AddressReviews` mode), each thread is checked for:

- Whether the request still stands against current code — a stale request gets a reply, not a change.
- Whether the proposed fix would be bloat in context; if so it's reverted rather than committed.
- Whether the diff contains only intended changes, with no debug artifacts left behind.
- Whether reply and resolve happened together — both or neither, and never before the fix is live on the remote.
- Whether a refuted finding was recorded as a withdrawn finding (group 7).
