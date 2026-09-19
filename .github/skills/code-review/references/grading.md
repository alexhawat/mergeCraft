# Finding grading and verification

## Table of contents

1. [Three axes](#three-axes)
2. [Placement rule](#placement-rule)
3. [Collateral rule](#collateral-rule)
4. [Confidence ladder](#confidence-ladder)
5. [Verification loop](#verification-loop)

Every surviving finding is graded on three independent axes before placement.
The grade decides where the finding lands — it is not decoration.

## Three axes

### Category

Functional Correctness · Data Integrity & Atomicity · Security & Privacy ·
Stability & Availability · Performance & Scalability · Maintainability & Code
Quality.

Pick by **consequence**, not syntax. A SQL string in a log line might be
Maintainability; the same string built from user input is Security.

### Severity

| Value | Meaning | Blocks merge? |
| --- | --- | --- |
| Critical | Data loss, security breach, or production outage if shipped | yes |
| Major | Real fallout if shipped; must fix before merge | yes |
| Minor | Worth fixing; ships without it | no |
| Trivial | Nit; style or polish | no |

`Critical` and `Major` are **blocking severities**. Everything else is advisory
for merge gates.

### Effort

| Value | Meaning |
| --- | --- |
| Quick win | Contained, obvious fix in this PR |
| Heavy lift | Design work, multi-file change, or migration |
| Low value | Correct but not worth the churn |

## Placement rule

**Mechanical placement** — no judgement call at the anchor:

- `Trivial` **or** `Low value` → bullet in the body's **Nitpicks** list, never an
  inline comment.
- Everything else → inline comment at its line with triage tag
  `_{category}_ | _{severity}_ | _{effort}_`.

**Why this rule exists:** inline anchors are expensive attention. Spending them on
nits trains authors to ignore every comment from this reviewer. Under-grading a
real blocker to Trivial hides merge risk; over-grading a nit to Major burns
credibility. Honest grading is the precision half of the job.

Agent findings that overflow the inline budget land in `### 🗂 Deferred findings`
(non-blocking, server-appended). Analyzer overflow uses `### 🔧 Mechanical findings`.

## Collateral rule

Every `Critical` or `Major` finding names **collateral damage** — what else must
move with the fix: callers, tests, docstrings, configs, migrations, or sibling
files. List collateral in the finding payload and repeat under an **Also update:**
bullet in the inline body.

Collateral is **not** required for `Minor` or `Trivial` findings.

Any collateral claim about code the diff does not contain must ship with evidence
(quoted command output or cited file). Without evidence, downgrade to a question
or drop per the §6 filter.

## Confidence ladder

| Value | Use when |
| --- | --- |
| certain | you read the cited code and the mechanism holds |
| likely | strong evidence but one assumption remains |
| possible | hypothesis worth naming; usually downgrade or verify before blocking |

Do not block merge on `possible` alone without verification. Escalate confidence
or drop.

## Verification loop

Every `Critical` / `Major` finding is a **hypothesis** until a second read-only
pass confirms it.

1. **Draft** findings with evidence attached.
2. **Dispatch** `mcp__mergecraft__verify_agent_findings` for your own Critical/Major
   rows (and treat analyzer/CI hits the same way).
3. **Record** each verdict with `mcp__mergecraft__record_finding_verdict`:
   - **confirm** — publish as drafted;
   - **downgrade** — re-grade severity/category;
   - **drop** — write reason under
     `## Withdrawn review findings (known non-issues)` so the claim stays refuted.

Bounds:

- `Minor` and `Trivial` are never verified.
- Fingerprints already under withdrawn findings are skipped outright.
- Dispatches are capped by `review.verificationBudget` (spent Critical before Major).

The verifier is a secondary signal — it never overrules a deterministic tool
result. On high blast-radius lanes, a lone `drop` may escalate rather than write
withdrawn memory immediately.

Only findings that survive this loop may block merge or appear as blocking rows
in the terminal verdict.
