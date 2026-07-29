# What mergecraft checks for

> **Doc status (W7 + catalog C6):** §2 describes the analyzer platform and the expanded
> P0–P3 catalog. Long-tail tools default to **disabled** unless repo config or detection
> enables them.

Every check mergecraft applies when it reviews a pull request, grouped by what it is looking at.

A quick orientation before the lists:

- Most of these are **judgment checks** carried out by the reviewing agent, not scripted rules. There is no rule engine — the behavior lives in the `Review` and `IncrementalReview` mode prompts in [`src/mergecraft/modes.py`](src/mergecraft/modes.py).
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

---

## 1. Code correctness and risk

The reviewer reads the whole diff itself, then picks the **lenses** the PR actually warrants and investigates each as a falsifiable question — optionally dispatching a `mergecraft-reviewer` subagent per lens so they run in parallel. Nothing here is a fixed pass; a docs-only diff gets none of it.

**Always in play**

- **Correctness and invariants** — bugs, races, error handling, edge cases, state-machine boundaries.
- **Data integrity and atomicity** — for any diff that writes persistent state: is the write ordered after the thing it records is confirmed, or before? does failing halfway leave a half-committed state with no rollback? is a retry idempotent, or does it double-apply?
- **Impact** — stale references left in code, tests, docs, configs, or UI after a rename or removal.
- **Copy vs code** — does every human-readable string still match what the code does? Help text, menu labels, error messages, `--help` output, README and doc claims, and the PR description's own promises.
- **Holistic** — does the PR make sense as a whole? Symmetric flows: a delete for every create, a rollback for every migration.

**Picked when the diff warrants it**

- **Security** — new endpoints, authorization, input validation, secret handling, replay / CSRF / injection, cross-tenant isolation.
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

Each gate returns one of four statuses; only **`failed`** is a finding:

| Status | Meaning |
|---|---|
| `passed` | ran, exit 0 |
| `failed` | ran, non-zero exit — a finding |
| `timed_out` | exceeded the per-gate timeout |
| `unavailable` | executable not installed — judged nothing |

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

**Trust tiers (D7):** `trusted` (same-repo PR, `workflow_dispatch`, offline `diff-review`) vs `untrusted` (fork PR / `pull_request_target` — no secrets, network deny-by-default, no PR-authored command construction; trusted-only manifests skip with reasons). `shell: disabled` withholds both gate and analyzer tools on PR events; offline `diff-review` runs analyzers at trusted tier without shell.

**Scoping (D6):** analyzers run on **head** by default; findings outside the diff hunks are dropped unless the path is an explicit exception (new file, dependency manifest, lockfile, workflow, migration). `introduced_by_pr: unknown` when no base run happened — never implied `true`.

**Clustering (D12):** one defect from multiple tools publishes **one** finding with corroborating evidence and raised `confidence`.

**Verification (D11):** Critical/Major analyzer hits are **hypotheses** until the read-only `mergecraft-verifier` subagent confirms, downgrades, or drops them. Drops write a reason under `## Withdrawn review findings (known non-issues)`.

**Noise budget (D14):** inline analyzer slots cap at **8** (W0.2 measurement); overflow lands in `### 🔧 Mechanical findings`. Agent findings win ties; Trivial/Low value never inline.

**Lockfile (D24):** `.mergecraft/analyzers.lock` records resolved tool id, version, source, and SHA256; the pre-merge **Analyzers** row echoes the digest.

### CI pipeline intelligence (`get_check_suite_logs`)

When CI failed on the PR head, mergeCraft reads GitHub Actions check-suite logs via `get_check_suite_logs` and normalizes failures behind `GitHubActionsProvider`.

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

Implementation: [`src/mergecraft/ci/review.py`](src/mergecraft/ci/review.py), [`src/mergecraft/ci/cluster.py`](src/mergecraft/ci/cluster.py), [`src/mergecraft/mcp/check_suite.py`](src/mergecraft/mcp/check_suite.py).

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
- Change-impact extraction (`impactPath`) is treated as an explicitly incomplete set of leads — never a substitute for reading the diff.
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

## 5. Finding grading

Every surviving finding is graded on three independent axes before it is placed. The grade decides placement, so it isn't decoration.

- **Category** — picked by where the *consequence* lands, not what the code looks like: Functional Correctness · Data Integrity & Atomicity · Security & Privacy · Stability & Availability · Performance & Scalability · Maintainability & Code Quality.
- **Severity** — Critical (blocks merge) · Major (real fallout if shipped) · Minor (worth fixing, ships fine without) · Trivial (nit).
- **Effort** — Quick win (contained, obvious) · Heavy lift (needs design, spans files, or has migration implications) · Low value (correct, not worth the churn).

Then placement is mechanical:

- `Trivial` **or** `Low value` → a bullet in the body's Nitpicks list, never an inline comment.
- everything else → an inline comment at its line, tagged `_{category}_ | _{severity}_ | _{effort}_`.

The axes are also a sweep: a PR that writes persistent state with no Data Integrity & Atomicity finding gets one more look before the reviewer concludes there was nothing there.

Values live in [`src/mergecraft/review_taxonomy.py`](src/mergecraft/review_taxonomy.py); a test asserts the prompt still names every one of them.

## 6. Findings that get dropped

What mergecraft deliberately does **not** report — this is most of what keeps a review readable:

- Praise, and style preferences the repo doesn't enforce.
- Speculative or unverified claims. Any claim about code the diff doesn't contain must ship with an `Evidence` section quoting the command that settles it; if the reviewer can't run one, the finding is downgraded to a question or dropped.
- Problems in pre-existing code unrelated to the PR. The test is whether the root cause lives in lines this PR added or modified — unless the PR plausibly introduced or amplified the regression.
- Anything not actionable.
- Anything already refuted in the learnings file (see next group).
- **Bloat-shaped findings** — proposed fixes that would add defensive checks for cases that can't happen, abstractions used once, comments restating obvious code, tests asserting tautologies, or "just-in-case" guards. The bar for an inline comment is sound **and** correct **and** elegant; a change that improves only one of the three makes the codebase worse.
- On `IncrementalReview`, anything that restates feedback a prior review already gave.

## 7. Memory across runs

- **Withdrawn findings** — when an author refutes a review finding and `AddressReviews` accepts the pushback, it records the *reason* in `.mergecraft/learnings.md` under `## Withdrawn review findings (known non-issues)`. Later reviews read that section first and treat it as binding, so a false positive is argued once instead of on every PR.
- **Finding fingerprints** — each inline comment is stamped server-side with a content hash of its path and body (`<!-- mergecraft-finding:v1:… -->`). Whitespace and case are normalized, so a re-raised finding is recognizable across runs even when reworded.
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

## 9. Address-reviews checks

When mergecraft is on the receiving end of review comments (`AddressReviews` mode), each thread is checked for:

- Whether the request still stands against current code — a stale request gets a reply, not a change.
- Whether the proposed fix would be bloat in context; if so it's reverted rather than committed.
- Whether the diff contains only intended changes, with no debug artifacts left behind.
- Whether reply and resolve happened together — both or neither, and never before the fix is live on the remote.
- Whether a refuted finding was recorded as a withdrawn finding (group 7).
