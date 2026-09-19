---
name: code-review
description: >-
  Reviews a pull request or diff in the mergeCraft repository and produces typed,
  evidence-backed findings with a blocking verdict. Use when reviewing a PR, a
  branch diff, or staged changes here; when asked "is this safe to merge";
  when grading or placing review findings; or when running mergeCraft against
  this repo. Covers correctness, data integrity, security, stability,
  performance, and maintainability, with the repo's own gates as evidence.
license: Apache-2.0
metadata:
  mergecraft.doctrine-version: "1"
---

# Reviewing code in mergeCraft

A mergeCraft review is a falsifiable audit of one diff: typed findings anchored to
evidence, graded on three axes, filtered hard, then one terminal verdict. A good
review is not the one with the most comments — it is the one whose blocking
concerns survive verification and whose silence means the author can merge.

This file is **self-sufficient**. A reviewer that reads only `SKILL.md` can run a
correct, complete review of this repository. The `references/` files add depth;
they are never prerequisites. Nothing in this skill tree links outside
`.github/skills/code-review/`.

> **For humans:** `REVIEW-CHECKS.md` is the consumer-facing check catalog;
> `docs/REVIEW-DOCTRINE.md` is the rationale and rejected alternatives. This
> directory is the agent-facing instruction bundle mergeCraft injects at review time.

## The four rules

These four are absolute. Everything else in this file is judgement. Each rule
states its reason so you can generalise to cases this file never anticipated.

1. **No finding without evidence you can point at.** A claim must cite a file and
   line, a diff hunk, tool output, or a retrieved artifact. Without an anchor it
   is a question — ask it in the summary or drop it. Unfalsifiable comments teach
   authors to ignore this reviewer.

2. **Never re-raise a withdrawn finding.** The section
   `## Withdrawn review findings (known non-issues)` in the learnings file is
   binding. Re-litigating a refuted finding is worse than missing a real one,
   because it proves this reviewer does not remember prior pushback.

3. **Every blocking concern in the summary exists as a findings row.** Prose in
   the summary is read by no gate. If it blocks merge, it must appear in the
   structured `findings` array with severity, category, and evidence.

4. **Exactly one terminal verdict.** Call `approve` or `request_changes` once,
   after findings survive verification. The verdict follows from the findings —
   never the other way around.

## Review progress

Copy this into your response and check items off as you go.

```
- [ ] 1. Scope    — full diff read end-to-end; coverage checklist built
- [ ] 2. Evidence — repo gates + analyzers run; withdrawn findings read
- [ ] 3. Triage   — what kind of change is this; trivial or not
- [ ] 4. Lenses   — load-bearing questions named, or none
- [ ] 5. Findings — drafted, evidence attached, graded
- [ ] 6. Filter   — drop list applied; blocking findings verified
- [ ] 7. Verdict  — one terminal call
```

## 1. Scope

Read the **complete diff** before anything else. Use the diff table of contents and
file line ranges as a coverage checklist. A reviewer that samples the diff writes
findings about the part it sampled and stays silent about the rest — and silence
reads as approval.

Then pull **targeted** context: the touched functions, their callers, the tests
that exercise them, the interfaces they cross. Not the whole repository. More
context measurably makes frontier models worse at this task; stay on the blast
radius.

## 2. Evidence before opinion

Run the repo's own gates first and quote them. "`make lint` fails on this file"
is a finding nobody argues; "consider sorting this" is one everybody does.

Three outcomes mean **no signal** — report them as skipped, never as findings:

- the tool is not in your toolset at all;
- the tool returns `ran: false`;
- a gate status is `unavailable`, `declared-but-cannot-run`, or `timed_out`.

Only `failed` is a finding. Never substitute your own linter, formatter, or
interpreter to fill a gap — a gate run under the wrong toolchain version
manufactures findings.

Read `## Withdrawn review findings (known non-issues)` **now**, not at drafting
time. It changes what you bother investigating.

## 3. Triage

Name what kind of change this is: which domain, which seams, which external
contracts, which user-visible surfaces.

**Genuinely trivial — skip to the verdict:** doc typo, whitespace-only,
comment-only, lockfile or generated-code regeneration, mechanical rename whose
only effect is import paths, low-risk dependency patch bump.

**Looks trivial but is not — small diff, large blast radius:**

- one-line changes to SQL, regex, auth, billing, permissions, or signature
  verification;
- a flipped feature-flag default, retry/timeout constant, or money/tax constant;
- a changed HTTP method, redirect URL, response code, or comparison operator;
- a renamed public API surface or new direct dependency;
- a "typo fix" in user-facing copy that changes meaning;
- a semantic one-liner buried in a formatting-only diff.

Read the shape, not the line count.

## 4. Lenses

Name the load-bearing questions you cannot resolve yourself. A question is
load-bearing only when its answer could change the verdict, and falsifiable only
when evidence could settle it. "Another look for confidence" is neither.

Two framings:

- **Themed lenses** across the whole diff (correctness, security, performance).
- **Subsystem lenses** for high-stakes domains (auth, billing, webhooks, schema
  migration). For those domains, lead with the subsystem lens — "the billing lens"
  primes double-charge and refund-race failure modes that a generic correctness
  pass misses.

Run `mergecraft lens list` for the registry — each entry carries its id,
triggers, rubric, and required evidence. Do not work from a remembered list.

## 5. Findings

Every finding carries six fields before you place it:

| Field | Value |
| --- | --- |
| Category | one of the six taxonomy categories (see references/grading.md) |
| Severity | Critical · Major · Minor · Trivial |
| Effort | Quick win · Heavy lift · Low value |
| Confidence | certain · likely · possible |
| Evidence | exact file and line, tool output, or retrieved artifact |
| Why | one sentence of consequence, not of mechanism |

**Placement is mechanical:** `Trivial` **or** `Low value` → a bullet in the
body's Nitpicks list. Everything else → an inline comment at its line.

The cost of a false positive is not the minute spent reading it — it is the team
learning to skip every comment this reviewer ever leaves. Grade honestly;
inflating a nit to Major to justify an inline anchor is the habit that makes a
reviewer ignorable.

**Category is a sweep, not a menu.** A PR that writes persistent state with no
Data Integrity & Atomicity finding is worth one more look before concluding there
was nothing there.

**Hunt for non-anchored concerns too:** deletion plans for code this diff
shadows; rollout sequencing and in-flight state; coverage the diff implies but
does not add; scope questions only a human can answer. On substantial PRs at
least one exists — if you cannot think of any, the bar is too high, not the PR
too clean.

See [references/grading.md](references/grading.md) for axes, placement, collateral,
and the verification loop.

## 6. What gets dropped

The drop list is most of what keeps a review readable:

- Praise and style preferences the repo does not enforce.
- Speculative and unverified claims.
- Findings whose root cause predates this diff.
- Anything already withdrawn.
- Anything not actionable.
- Bloat-shaped fixes — defensive checks for impossible cases, abstractions used
  once, comments restating obvious code, tests asserting tautologies,
  just-in-case guards. The bar is sound **and** correct **and** elegant; a change
  that improves one by degrading another makes the codebase worse.

**Silence is a result.** If nothing survives this filter, say so explicitly and
approve. An empty review from a reviewer that looked hard is a valid outcome and a
good one. Manufacturing a finding to look diligent is the failure mode this
section exists to prevent. Route silence through §7 — do not stop after §6 without
a terminal verdict.

## 7. Verdict

The terminal call is exactly one of `approve` or `request_changes`, with a
`summary` and a `findings` array. Match the opening callout tier to what the
author should actually do next.

- **`approve`** — no blocking findings survive verification; say so plainly.
- **`request_changes`** — at least one Critical or Major finding blocks merge;
  every blocking concern in the summary must have a matching findings row.

The server **rejects** `request_changes` with an empty `findings` array — that is
enforced, not a style preference. `approve` over a verifier-confirmed Critical or
Major blocker is also rejected.

When silence is the outcome: call `approve` with an empty `findings` array and a
summary that states what you read, what gates you ran, and that nothing actionable
survived the filter.

See [references/tools.md](references/tools.md) for the call in each environment.

## Tools

Three capability tiers share this one skill. Use the tier that matches your
runtime; degrade steps — never skip them silently.

**Tier 1 — mergeCraft MCP (full):** `mcp__mergecraft__checkout_pr` establishes
scope and returns `diffPath`. In the same turn call
`mcp__mergecraft__run_static_checks` and `mcp__mergecraft__run_analyzers` with
changed paths; when CI failed on the head, call
`mcp__mergecraft__analyze_ci_failures`. Before publishing, hand Critical/Major
agent findings to `mcp__mergecraft__verify_agent_findings` and record each
verdict with `mcp__mergecraft__record_finding_verdict`. Finish with exactly one
`mcp__mergecraft__submit_review_verdict` (`verdict`, `summary`, `findings`).

**Tier 2 — Copilot / hosted code review (no MCP):** Read the PR diff from the
host UI. Run repo gates locally when you have shell access (`make lint`,
`make typecheck`, scoped pytest). Draft findings as inline review comments with
the triage tag; post an approve or request-changes review through the host. You
cannot call `submit_review_verdict` — make the summary and inline comments
self-contained so a human can act without mergeCraft's structured export.

**Tier 3 — bare agent (file access only):** Read the diff artifact and changed
files directly. Note which gates you could not run. Produce findings with the six
fields above; end with an explicit approve or request-changes recommendation and
the same discipline on evidence and silence.

## References

- [references/checks.md](references/checks.md) — the check catalog by category
- [references/grading.md](references/grading.md) — axes, placement, collateral, verification
- [references/repo-traps.md](references/repo-traps.md) — mergeCraft-specific failure modes
- [references/tools.md](references/tools.md) — what to call in each environment
