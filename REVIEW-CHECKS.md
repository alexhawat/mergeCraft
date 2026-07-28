# What mergecraft checks for

> **Doc status (W6):** This file is **stale-with-reason** until Wave W7 rewrites §2 for the analyzer platform (actionlint, zizmor, ShellCheck, Hadolint adapters ship as manifests; review integration lands in W7).

Every check mergecraft applies when it reviews a pull request, grouped by what it is looking at.

A quick orientation before the lists:

- Most of these are **judgment checks** carried out by the reviewing agent, not scripted rules. There is no rule engine — the behavior lives in the `Review` and `IncrementalReview` mode prompts in [`src/mergecraft/modes.py`](src/mergecraft/modes.py).
- Exactly one check group is **mechanical**: [Mechanical gates](#2-mechanical-gates) shells out to your repo's own linter.
- Groups 1–3 are the ones that produce findings. Groups 4–8 govern how findings are graded, placed, filtered, and formatted — they are why the review stays short.

## Contents

1. [Code correctness and risk](#1-code-correctness-and-risk) — the review lenses
2. [Mechanical gates](#2-mechanical-gates)
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

## 2. Mechanical gates

The one group that runs commands instead of reading code. Always **your repo's own** gate:

- **Declared gates** — whatever you list under `staticChecks` in `.mergecraft/config.yaml`. A `{files}` token expands to the diff's changed paths, and `suffixes` skips the gate when no matching file changed.
- **Discovered gates** — with nothing declared, mergecraft looks for `lint`, `format-check`, `typecheck`, and `ci-static` targets in your `Makefile` and runs the ones that exist. Skipped entirely when `make` isn't installed, since every command it would produce is unrunnable.
- **Nothing found** → reported as skipped. mergecraft will **not** substitute a linter or interpreter of its own, because a gate run under the wrong toolchain version invents findings. (`except A, B:` is a syntax error on Python 3.13 and perfectly legal on 3.14.)

A failing gate becomes a finding that quotes the exact command and its output, so "consider sorting this" becomes "`make lint` fails on this file". Gate results also tell the reviewer which conventions your repo actually enforces, so it stops inventing ones you don't.

Each gate comes back as one of four statuses, and only **`failed`** is ever a finding:

| Status | Meaning |
|---|---|
| `passed` | ran, exit 0 |
| `failed` | ran, non-zero exit — a finding |
| `timed_out` | exceeded the per-gate timeout |
| `unavailable` | the executable isn't installed here, so it judged nothing |

**When gates run at all.** A gate executes commands your config names, so on a pull request it executes commands the PR author controls. That is what `shell: disabled` exists to forbid, so under that setting the tool is not offered and the pre-merge row is skipped. The offline `mergecraft diff-review` path always has it, because there the config and the working tree both belong to whoever started the run.

One consequence worth knowing: the containerized GitHub Action image ships neither `make` nor your project's toolchain, so `make`-based gates report `unavailable` there and do their real work on the local review path.

Implementation: [`src/mergecraft/review_checks.py`](src/mergecraft/review_checks.py), exposed to the agent as the `run_static_checks` tool.

## 3. Pull request hygiene

Assertions about the pull request itself rather than its code. These always appear, as a small **Pre-merge checks** table at the top of the review body:

- **Title** — does it name the main change? Flagged when it covers only part of the diff, or names something the diff doesn't do.
- **Description** — does it explain what changed and why, and does every claim in it hold against the diff?
- **Linked issues** — for each issue the PR closes, is every stated requirement actually covered?
- **Scope** — does the diff do things neither the description nor a linked issue asked for? Out-of-scope paths get named.
- **Mechanical gates** — the result from the group above.

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
