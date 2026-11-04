# What mergecraft checks for

> **Agent-facing artifact:** `.github/skills/code-review/` is what mergeCraft injects
> into the reviewing agent at runtime; this file is the human-facing catalog of the
> same checks.

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
10. [Trajectory checks](#10-trajectory-checks)
11. [Deterministic run record](#11-deterministic-run-record)
12. [Policy rules](#policy-rules) — repository rules enforced at the approval gate

---

## Mechanical evidence — what counts

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
  packet's `run_health` section at assembly time.
- **Policy rows** — typed `Finding`s with `tool="policy"`, computed by
  `src/mergecraft/policy/review.py` from the repository's own rules
  ([Policy rules](#policy-rules)). They are mechanical evidence like any other
  typed row, so they block through the same predicate — and the agent's `drop`
  valve never retires one.
- **`DeterministicCheck` rows** — one per declared `staticChecks` or
  discovered Makefile target. Status is one of five: `passed`, `failed`,
  `timed_out`, `unavailable`, `declared-but-cannot-run`. **Only
  `failed`** is a negative finding; **only `passed`** is a positive
  signal. The other three are honest skips, never silent passes.
- **CI check-runs** — raw `check_suite` data from `mcp/check_runs.py`
  plus the cluster/blame/flaky annotations from `src/mergecraft/ci/`.
- **The agent's `approved` boolean** — **NOT** mechanical evidence. It
  is recorded on the packet as `self_assessment` and is advisory only;
  a self-assessment-only run cannot reach `auto_merge` (pinned by
  `tests/evidence/test_self_assessment.py`).

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

A behaviour-verification report (from `mergecraft verify-behavior`, consumed
via `--verification-report`) is **not** a typed `Finding` and is **not**
mechanical evidence for the approval gate. It is a separate artifact: page
text and console output the change under review can control, so it is fenced
before any prompt. Treat it as evidence about the running app, not a
substitute for reading the diff. `skipped` and `blocked` are not a pass —
`blocked` names the missing input and stays visible; omitting the report
leaves the review unchanged.

The merge-evidence packet's `decision` row is computed by
`mergecraft.agents.gates.decide_approval(findings, *, run_succeeded,
tier)` from these structural inputs. When the packet is given directly
to `decide_approval(packet, …)`, the explicit `Decision` row on the
packet wins over every other signal — including the recorded
`self_assessment`.

## Terminal verdict vs structural verdict (VP2)

A review run is not complete until the agent records a **terminal
submission** through `submit_review_verdict`. Provider success and review
prose are not a verdict, and recording a verdict is not publishing it: the
agent records, and the run publishes.

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
maps to `RunOutcome.inconclusive`, same as no submission at all. A policy row
is one of those blockers, and it is never withdrawable: `drop` retires agent
claims, not a row the repository's own rules produced.

**Why prose is not authoritative.** Text such as "LGTM" in `result.output`
has never been an input to `decide_approval` and cannot approve a pull
request. A run whose provider returned successfully but never called
`submit_review_verdict` now reports `inconclusive` (`neutral` check
conclusion) instead of `passed`.

**The run publishes the recorded verdict.** After the final attempt's
submission is accepted, the run posts it to GitHub as one review whose inline
comments are the submission's findings. It posts once per head: if the agent
already published the same verdict, nothing is posted again. If an earlier
attempt already published a *different* verdict on the same head, nothing is
posted either (GitHub cannot take a review back, and a second one would
duplicate every inline thread), and the run reports `inconclusive`, naming the
verdict GitHub shows and the one it recorded. A published review that shows
fewer findings inline than were recorded lists the missing ones in the publish
response. A recorded verdict that never reached GitHub reports `inconclusive`
with its own reason. Each fresh run still posts its own review.

**Changed-line coverage.** A verdict is only worth reading if the whole change
reached the reviewer. At the end of the run mergeCraft accounts for every
changed hunk of the PR diff: a hunk is *covered* when it was in the diff the
reviewer was handed, or when an observed read covered part of it. Absence of
read evidence counts as uncovered, not unknown. Files GitHub sent line counts for but no patch (`no_inline_patch`)
and files beyond the files-API page cap (`diff_truncated`) are listed and can
never be cleared, because there are no lines to hand back; generated, minified
and vendored hunks removed by policy are listed as `excluded_generated` and do
not count against completeness. Before the verdict is accepted, one nudge names
exactly the unread ranges so the reviewer can read them and submit again; that
nudge fires once per session. If anything is still uncovered, the run is
`inconclusive` (a `neutral` check)
even though a verdict was submitted; a Critical or Major finding still makes
`mergecraft-approval` conclude `failure`. The checks and the run record state
it (`Coverage: 41/44 hunks, 3 uncovered → inconclusive`) and the packet's
`coverage` section carries the detail. Set `review.coverage.onIncomplete: warn`
to keep the verdict and only report the gap. This proves delivery, not
comprehension: a driver's native file reads never cross mergeCraft's wire.

**Deterministic triage before dispatch (`review.fastPath`).** Off by default.
When enabled in the operator's base-side config (a `pull_request_target`
run — head-side config is never honoured), mergeCraft decides from the diff
alone, before the MCP server and the agent exist, whether an LLM review is
worth running. Five recognizers answer "is *every* change in this diff of this
kind?": `pinBump` (each changed line pair differs only in a 40-hex SHA or
`sha256:` digest, always the same single old → new pair), `prose` (only
`.md` / `.txt` edits outside code fences, front matter and high-stakes
paths, never a dependency manifest, lockfile or agent-instruction file, proved
against the head-side text), `whitespace` (the same tokens before and after;
indentation counts in whitespace-sensitive languages), `generated` (only
lockfiles or generated paths, with no manifest or generator config beside
them) and `commentOnly` (only `//` line comments changed, in a closed list of
`//`-comment languages — `.ts .go .java .kt .c .h .cc .cpp .hpp .cs .swift`.
JavaScript (`.js`, which can hold JSX) and `.jsx` / `.tsx` are excluded because a
JSX text child can start with `//` and render; Rust because a lifetime's lone `'`
defeats the quote check; `Package.swift` because SwiftPM reads its first comment;
and Go `_test.go` files (an `// Output:` comment is a test assertion) and Go files
marked `DO NOT EDIT` (generated). A Java file with a `\u` unicode escape
(translated before lexing, even in comments) and a C-family file with `??` (a
trigraph can splice the next line) are refused. Each changed line must be `//`,
one space and a plain alphabetic first word, so `//go:build`, `// +build`, `///`
and `// @ts-ignore` never match; a removed line must be replaced by an added
one. The diff and the head-side file must be printable ASCII and are split on
newlines only, and a file with a backtick, a raw-string marker, any `/*` or a
quote left open at the end of a line is refused, so the lexer over the head text
proves every changed line is a comment; every `#`-comment language is refused.
For the listed languages a recognised edit proves no runtime change, but a
comment can still carry tool directives for linters, coverage or code
generators; a directive-word list (`fallthrough`, `Output`, `nolint`,
`NOLINTNEXTLINE`, `istanbul`, `IWYU`, `pragma`, `build`, `Code`, …) refuses the
known ones on a best-effort basis). A mixed diff matches nothing and gets a
full review. `skipLlm` opts each
recognizer in; a pin bump also needs every `pinBump.requireChecks` check to have
passed on the head SHA **from a GitHub App named in
`pinBump.trustedCheckApps`** — a check-run name is chosen by its creator, and
the `github-actions` runs of a `pull_request` workflow come from the head ref, so
neither can vouch. A skipped run posts the `mergecraft` check stating
`Tier: skip (pinBump) — no LLM review ran`, names the checks it relied on,
**never grants `mergecraft-approval`**, and records the tier in the evidence
packet and the shadow log. With `review.fastPath.lite.enabled`, the two cases a
skip leaves out — a recognizer that matched but is not in `skipLlm`, and a pin
bump whose verifying checks have not passed — get a `lite` review instead: one
non-streaming call to an operator-registered OpenAI-compatible provider
(`lite.provider`, `lite.model`), with the diff inlined and no checkout, MCP
server, specialists or verifier. The `lite.tokenCap` (default 50,000) is checked
before the call: an upper-bound prompt estimate plus `maxOutputTokens` over the
cap, a missing credential or an unregistered provider downgrades the run to the
full review, and a diff is never truncated. A `lite` run posts its findings as a
review comment, states `Tier: lite — single-call review, cap N tokens`, records
the cap and the tokens used in the evidence packet, and **never grants
`mergecraft-approval`**: the `mergecraft` check is `neutral`, or `failure` on a
Critical or Major finding, and usage over the cap or a malformed answer is
`inconclusive`. Any read
failure, truncated listing or file without a patch is a full review. The PR
title, body and labels are never inputs.

**Ignored paths (`ignore_paths`, `review.ignorePaths`).** Changed files whose
repo-relative path matches an ignore glob are cut from the diff the reviewer
reads (`diffPath`, `incrementalDiffPath`) and from the changed-line coverage
universe, so they are out of scope rather than unread. A rename or copy is matched on both
its source and its new name and leaves review only when both are ignored, so
`git mv src/auth.py CHANGELOG.md` is still reviewed. `checkout_pr` names them
in `ignoredPaths`, and the review body lists them under "Not reviewed (ignored
by config)". The globs are the `ignore_paths` Action input, `review.ignorePaths`
and, unless `review.ignorePathDefaults: false`, the defaults: `**/CHANGELOG.md`,
`**/*.lock`, `**/package-lock.json`, and generated or minified files (a
generated file stays in scope when its generator config changed too). The YAML
half is read from the operator's side only — the base snapshot of a
`pull_request_target` run, the base commit's config on any other pull request —
so a pull request cannot ignore its own files. When the complete file listing of
a `pull_request` / `pull_request_target` run is ignored, the agent never starts:
the run passes with `Tier: skip (ignorePaths) — no LLM review ran`, "nothing to
review", and `mergecraft-approval` is left to a human. A run the gate does not
skip — a comment-driven review, or a failed or truncated listing — is never
handed an empty scope it could approve: when the checkout's complete diff holds
only ignored files, it records the same skip tier, so `mergecraft-approval` stays
neutral and no GitHub approval is posted whatever the agent submits; when the
files-API listing was truncated, nothing is filtered and the whole diff is
reviewed. The coverage gate likewise never filters down to an empty scope.

**Fallback interaction.** Semantic fallback advances when
`terminal_submission_received` is false — whether because no submission
was recorded or because the validator rejected one. A valid
`request_changes` verdict with confirmed findings is a usable result and
does not trigger fallback.

## 1. Code correctness and risk

The reviewer reads the whole diff itself, then picks the **lenses** the PR actually warrants and investigates each as a falsifiable question — optionally dispatching a `mergecraft-reviewer` subagent per lens so they run in parallel. Nothing here is a fixed pass; a docs-only diff gets none of it.

Each review round records which lenses were **selected**, which were **skipped** (with reasons from deterministic routing), and which were **actually dispatched**. That set is written into the review metadata HTML comment and the merge-evidence packet so the next round — and incremental complement routing in a follow-up review — can read what already ran without re-deriving it from prose.

**Run lifecycle (S1)** — a failed or timed-out trusted-tier `setupScript` yields `RunOutcome.inconclusive` (neutral check conclusion), not a review. An under-provisioned tree never receives a review verdict. See [`docs/config-failure-policy.md`](docs/config-failure-policy.md#setup-script-failures) for the policy table and operator checklist.

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

**Execution preference:** `repo-native` → existing CI result → managed pinned binary → container → **skip with a named reason**. Skipped is skipped — never a finding, never a failed pre-merge row.

**Trust tiers:** `trusted` (same-repo PR, `workflow_dispatch`, offline `diff-review`) vs `untrusted` (fork PR / `pull_request_target` — no secrets, network deny-by-default, no PR-authored command construction; trusted-only manifests skip with reasons). Offline `diff-review` runs analyzers at trusted tier without shell.

**`shell: disabled` (#35):** hardening the workflow no longer costs you the catalog. Repo-declared gates stay withheld — they run command strings the PR author controls — but mergeCraft's own **`managed` / `container` analyzers still run**, because their argv comes verbatim from a manifest mergeCraft ships and a repo-provided binary may not stand in for the pinned one. `repo-native` manifests are withheld, each with a named reason, since they exist to run the repo's own tool against the repo's own config. What a consumer sees on a `pull_request_target` + `shell: disabled` run: analyzer rows for the managed tools that matched the diff, `unavailable` rows naming why each other manifest was withheld, and the `staticChecks` gates reported as `declared-but-cannot-run`. The full runtime × shell × trust matrix is generated into [`docs/ANALYZERS.md`](docs/ANALYZERS.md).

**Scoping:** analyzers run on **head** by default; findings outside the diff hunks are dropped unless the path is an explicit exception (new file, dependency manifest, lockfile, workflow, migration). `introduced_by_pr: unknown` when no base run happened — never implied `true`. Every drop is recorded against the hit with the stage and a reason (see **Disposition ledger** below).

**Clustering:** one defect from multiple tools publishes **one** finding with corroborating evidence and raised `confidence`. A hit merged into a cluster is recorded `merged` and points at the surviving finding's fingerprint.

**Verification:** Critical/Major analyzer hits are **hypotheses** until the read-only `mergecraft-verifier` subagent confirms, downgrades, or drops them. Drops write a reason under `## Withdrawn review findings (known non-issues)` **and** are recorded against the hit in the disposition ledger (`dropped:verifier`, or `downgraded` with the old and new severity).

**Disposition ledger:** every raw analyzer hit gets a stable `hit_id` when it is parsed and must end with exactly one terminal disposition — `kept`, `merged`, `downgraded` or `dropped:<out_of_scope|baseline|withdrawn|generated|verifier>` — each with a stage and a non-empty reason. The packet carries the ledger, per-stage counts and the baseline-suppression audit rows ([`docs/evidence-packet.md`](docs/evidence-packet.md)), and the pre-merge **Analyzers** row shows it, for example `ruff 14 raw → 3 kept (9 out_of_scope, 2 baseline)`. If a stage loses a hit without recording it, the run is **inconclusive** and a run-scoped finding names the orphaned hit ids; blockers still win. SARIF ingested via `ciEvidence.sarifArtifacts` follows the same contract.

**Self-silencing (`self-silencing`):** a deterministic, in-process analyzer — no shell, eligible on every trust tier — that makes a PR's own reduction of scrutiny visible. It reports each **added** suppression marker (`# nosec`, `# noqa`, `# type: ignore`, `// eslint-disable-next-line`, `// @ts-ignore`, `#[allow(..)]`, `//nolint`, `// NOLINT`, `# rubocop:disable`, `@SuppressWarnings`, `# shellcheck disable=`, `nosemgrep`, `gitleaks:allow`) with the rule codes it silences — markers already on base are not reported — and it reports **what loosened** in `.mergecraft/config.yaml`, `ruff.toml` / `pyproject.toml [tool.ruff]`, ESLint config and scanner ignore files (an analyzer disabled, a rule added to `ignore`, a path excluded, a rule turned off, a budget lowered); pure tightening is not reported. `Major` for a loosening edit to mergeCraft config and for a suppression on a security rule, `Minor` for style-linter suppressions, one level higher on the `untrusted` tier. The suppression stays allowed; the finding says "justify in the PR or remove".

**A PR's own analyzer config never applies to its own review.** Analyzer settings (`analyzers.enabled`, `overrides.<id>.enabled`, the `antislop` `rules` / `ignore`, `baseComparison`, `inlineBudget`, `impact`) are resolved from the PR's **base** — the operator-owned base snapshot, or `git show <base sha>:.mergecraft/config.yaml` on events whose run-start tree is the PR head — and a symlinked config fails closed to built-in defaults with a named reason. A head-side change to `analyzers.*` is therefore *reported* by `self-silencing` but not *applied*: land analyzer-config changes in their own PR; they take effect from the next PR on. The packet records where the settings came from ([`docs/trust-policy.md`](docs/trust-policy.md), [`docs/evidence-packet.md`](docs/evidence-packet.md)). Edits to `.mergecraft/**` and analyzer/linter config also keep the PR out of the `eligible` blast-radius lane.

**Noise budget:** inline analyzer slots cap at **8**. Analyzer overflow lands in `### 🔧 Mechanical findings` (compact tool table). Agent overflow lands in `### 🗂 Deferred findings` with full finding text (non-blocking, server-appended). Agent findings win ties; Trivial/Low value never inline.

**Lockfile:** `.mergecraft/analyzers.lock` records resolved tool id, version, source, and SHA256; the pre-merge **Analyzers** row echoes the digest.

### CI pipeline intelligence (`analyze_ci_failures`)

When CI failed on the PR head, mergeCraft calls `analyze_ci_failures`, which wraps `get_check_suite_logs` and normalizes failures behind `GitHubActionsProvider`.

To discover a `check_suite_id` for a commit, call `list_check_runs` with the PR head SHA (or `get_check_suite` when you already have an id). Then pass that id to `get_check_suite_logs` or `analyze_ci_failures`.

**What is read**

- Failed workflow job/step names, exit codes, and redacted log excerpts
- Retry attempt history and **base-branch run fingerprints, read automatically**: for the workflows that failed on the PR head, the producer lists the base branch's recent completed runs, fingerprints the failing ones through the same pipeline as the head failures, and records the runs it used (`baseBranchRuns` in the tool result and on the run's CI evidence). Only a same-fingerprint `failure` clears; a passing or unrecognised base never does, and an unreadable base degrades to the unattributed report
- PR diff paths for blame overlap

**What is inferred**

- Root-cause clustering by failure fingerprint (twelve shards from one broken import → one finding)
- Flaky vs stable vs pre-existing classification from retry flips and base-branch evidence
- PR attribution (`caused_by_pr` vs `probably_not_this_pr` vs `unknown`) from diff overlap and same-fingerprint base-branch evidence — never asserted without evidence
- Truncation when more failures exist than the configured cap (default 3)

**What is explicitly not claimed**

- mergeCraft does not re-run CI, retry jobs, or push fix commits
- Non-GitHub providers (CircleCI, GitLab, Azure) are honestly stubbed — no silent empty results
- A failure outside the diff is **reported, not blamed** on the author
- When the evidence does not decide — no diff overlap and no same-fingerprint base-branch failure — the failure is **unattributed** and stays blocking; only a base-branch failure or a retry flip clears it
- Flaky failures are named flaky rather than treated as the author's defect

The review publishes `### 🚨 CI failures` with clustered root causes, flaky/blame verdicts, and redacted excerpts. The pre-merge **CI** row reports failure count, cluster count, flaky count, PR-attributed count, unattributed count, and whether truncation occurred. Inline CI comments may carry a one-click `suggestion` when the fix is a contained single-hunk edit; pushing a fix commit stays behind the existing `push` permission. Only an inline comment is posted for a `caused_by_pr` failure: an unattributed one has no proven hunk to anchor to.

**Recorded as evidence (#36).** Each clustered CI failure is also recorded as a `source: ci` finding on the run and carried into the [merge evidence packet](docs/REVIEW-DOCTRINE.md), keeping the blame verdict it was given: a failure attributed to this PR is `Major` / `introduced_by_pr: true`; a flaky or pre-existing one is `Minor` / `introduced_by_pr: false`; and an **unattributed** one — no diff overlap and no same-fingerprint base-branch failure — is `Major` / `introduced_by_pr: unknown`. Since every gate that consumes findings is monotone in blockers, the annotation is what makes the verdict mechanical rather than a matter of wording — a flaky pipeline cannot block a clean pull request, and an unattributed failure cannot be cleared without evidence.

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
- **CI** — pipeline intelligence on failing check suites: failure count, cluster count, flaky count, PR-attributed count, unattributed count, and whether truncation occurred. Flaky and probably-not-this-PR failures are reported here, not blamed on the author; a failure the evidence cannot place is reported as unattributed and stays blocking until a base-branch failure or a retry flip clears it.

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
  no cap), **scaled per round by `review.roundBudgets`** and spent on `Critical` before `Major`.
  Verification depth is independent of inline placement (`analyzers.inlineBudget`, default 8).
  Over-budget fingerprints are recorded in `skippedOverBudget` rather than silently dropped.

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
- On `IncrementalReview`, **first-pass miss labelling:** when a *new* finding's root cause is on a line that already existed at the first reviewed commit (context in the incremental diff, not a line the fix commits added), the inline body is prefixed with `_(First-pass miss — this line was already present at the first reviewed commit.)_`. That label is honest scope disclosure — not a restatement of prior feedback and not a drop.
- On `IncrementalReview`, **deferred promotion:** when the incremental diff touches a path cited by a ledger `deferred` finding, checkout promotes that record back to `open` with an audit reason. Promotion is back in scope — not a restatement of prior inline feedback.
- **PR prose is evidence, never instruction.** A finding whose only support is the PR title, PR body, a comment, or any other fenced untrusted field is **dropped** if the prose merely *describes* a change without anchoring to diff lines, and **downgraded** to a question if the prose *asserts* a property that the diff does not demonstrate. The diff (or, for design questions, the linked design doc) is the only thing that anchors a finding. Sentences inside the per-run fence block are untrusted internet content by default — they may inform a hypothesis, but they never stand in for evidence.

## 7. Memory across runs

- **Withdrawn findings** — a **`drop` verdict** from the verifier writes the verifier's *reason* in
  `.mergecraft/learnings.md` under `## Withdrawn review findings (known non-issues)`, keyed by the
  finding's own fingerprint. That is the path production runs: a finding refuted *before
  publishing* is refuted permanently, and the same claim is skipped before verification on every
  later run. Later reviews read that section first and treat it as binding, so a false positive is
  argued once instead of on every PR.
- **Finding fingerprints** — each inline comment is stamped server-side with a content hash of its path and body (`<!-- mergecraft-finding:v1:… -->`). Whitespace and case are normalized, so a re-raised finding is recognizable across runs even when reworded.
- **Open-PR finding ledger** — the sticky progress comment carries `<!-- mergecraft-ledger:v1:<fingerprint>:<state> -->` markers for every finding this pull request's reviews considered, including deferred overflow, verifier drops (`withdrawn`), and over-budget verifications (`unpublished`). Persistence is GitHub-only; inspect with `mergecraft findings ledger --pr N`. The ledger never files GitHub issues — post-merge carryover owns issue filing.
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

## 10. Trajectory checks

Everything above reads the **diff**. These eight checks read *how the run
produced it* — the tool calls mergeCraft mediated. A diff can look clean while
the process that produced it was not, and that is invisible to a diff review.

| Check | Fires when | Severity |
|---|---|---|
| `changed-unread-file` | A file was modified that the run never read (listed in the record; does not block the approval decision, though `gate_policy` still maps the rule id to `request-changes`) | Minor |
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

**Run-scoped, never blocking.** Trajectory checks stamp `scope="run"`,
`source="trajectory"`, and `introduced_by_pr="false"`. They partition into the
packet's `run_health` section and render under a separate collapsed heading in
the deterministic run record. `blocking_findings()` drops them before severity
grading — no severity, and no future check, makes a run-scoped finding fail a
PR. There is no separate trajectory verdict and no second required check-run.

**They never crowd out code findings.** Inline slots go to code findings first;
trajectory findings take only what is left and otherwise report in the body or
the run-health section.

## 11. Deterministic run record

Every run that resolves a PR number leaves exactly one authoritative sticky
progress comment, whether the agent published a review, posted no verdict, or
failed mid-run. Re-runs edit the same comment in place via the existing
sticky marker — they do not append a second one.

The comment and the published review body both render from
`render_deterministic_review_block()` in `findings/ledger.py`, so the two
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

`AddressReviews` is **not registered in production** — mergeCraft's production modes are
review-only and only review a diff; none of them addresses review comments or pushes commits.
The checks below describe that mode's design and are documented for contributors, not a
behaviour a shipped run performs: whether a request still stands against current code (a stale
request gets a reply, not a change); whether a proposed fix would be bloat in context (reverted
rather than committed); whether the diff contains only intended changes, with no debug artifacts
left behind; whether reply and resolve happened together — both or neither, and never before the
fix is live on the remote; and whether a refuted finding was recorded as a withdrawn finding
(group 7).

## Policy rules

A repository can ship versioned rules in `.mergecraft/policy/rules.yaml`, and
review enforces them at the approval gate. This is **policy rules**
(policy-as-code). It is not *gate policy* — what to do with a decision
(`gates.gateAction`). The two share a word and nothing else.

**What triggers a rule.** A rule applies when a changed file in the full pull
request diff matches its `scope`. There is no content detector: the scope match
*is* the trigger. A `blocking` rule scoped over `src/billing/**` therefore means
"a pull request touching these paths needs a waiver or a policy change", not
"the code contains a secret". Write scope tightly — a rule scoped `src/**` gates
every source change.

**What each enforcement mode does to the verdict.** The mode sets the
gate-facing severity of the single finding a rule contributes, and
`decide_approval` reads severity and nothing else:

| Mode | Effect on the gate |
| --- | --- |
| `blocking` | a non-blocking declared severity is floored to `Major`, so the rule blocks |
| `required` | `Major` until every key in `evidence.required` is available; `Trivial` after, when the declared severity was blocking |
| `warning` | a blocking declared severity is capped to `Minor` — visible, never blocking |
| `advisory` | a blocking declared severity is capped to `Trivial` — recorded, never blocking |

Whenever the mode changes the declared severity, the declared value is kept on
the finding's `evidence`, so a cap never hides what the rule asked for.

**Missing evidence blocks and says what is missing.** No in-run producer exists
yet for the evidence keys (`health_check`, `rollback_plan`, `contract_schema`,
`requirements`, `xrepo`), so a `required` rule that names one sits at `Major`,
and its row names every missing key. The way past it is a waiver.

**Where the rules come from.** Never the pull request under review. On a
`pull_request_target` run they come from the operator-owned snapshot captured
before checkout; on every other run from the pull request's **base commit**. A
pull request that edits, weakens, deletes or waives a rule therefore changes the
rules for the *next* pull request, after it merges — and review adds an advisory
row saying so. When no base commit can be read and the pull request touches
`.mergecraft/policy/`, nothing from its own copy is evaluated, and a blocking
row says the source could not be verified.

**Who may waive.** A waiver in `.mergecraft/policy/exceptions.yaml` must name
the rule (`rule_id`), still be unexpired at review time, and cover **every**
matched path — a partial waiver leaves the rule triggered on the rest. A fully
waived rule is still recorded, as a `Trivial` row naming the exception id,
approver and expiry. A waiver set that the pull request controls waives nothing.

**Unreadable files block.** A `rules.yaml` or `exceptions.yaml` that does not
parse produces one `Major` row naming the file and the parse error; it never
silently turns enforcement off. Dimensions a review cannot resolve — `language`,
`symbol`, and `branch` when the base branch is unknown — are treated as
matching, and the row's evidence names the dimension, so an unset context can
never fail open.

**No file, no rules.** A repository without `.mergecraft/policy/rules.yaml`
reviews exactly as it did before this feature existed. The example packs that
`mergecraft policy` lints, tests, explains and simulates against are authoring
material; review never loads them, because they assume a detector that does not
exist and would block every pull request touching `src/**`.
