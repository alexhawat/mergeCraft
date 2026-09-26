# mergeCraft glossary

Plain-language definitions for terms on the landing page and in consumer docs.

**Audience:** consumer (product and setup documentation)

mergeCraft uses a few precise terms. This page is the definition home — the landing
README links here on first use instead of repeating long explanations inline.

## Terms

<span id="trust-tier"></span>

### Trust tier

A **trust tier** is how much mergeCraft trusts the code it is reading: a pull request
from your own repository is trusted and gets secrets; a pull request from a fork is not,
and runs with no secrets and read-only tools.

Read more: [Security model](workflows.md#security-model) in `docs/workflows.md`,
[Operator trust policy](trust-policy.md) for the `trust.selfReview` knob.

<span id="typed-finding"></span>

### Typed finding

A **typed finding** is one review issue with a severity, a file location, and a short
explanation — the unit that drives inline comments and the merge gate.

Read more: [REVIEW-CHECKS.md](../REVIEW-CHECKS.md) — how findings are graded and gated.

<span id="blast-radius"></span>

### Blast radius

**Blast radius** is how wide the impact of a change could be — from small, isolated edits
to migrations or security-sensitive code that needs extra scrutiny.

Read more: [Blast-radius classifier](blast-radius.md).

<span id="harness"></span>

### Harness

A **harness** is the agent or CLI runtime that runs mergeCraft's review commands
(Claude Code, Codex, Cursor, and others).

Read more: [Compatibility matrix](compatibility-matrix.md).

<span id="verifier"></span>

### Verifier

The **verifier** is a read-only second pass that re-reads every Critical or Major finding
before it is published, so only confirmed issues reach the pull request.

Read more: [Review doctrine](REVIEW-DOCTRINE.md#verification-covers-every-source-including-ourselves-c6).

<span id="analyzer"></span>

### Analyzer

An **analyzer** is a deterministic tool (linters, scanners, workflow checkers) that
reports mechanically verifiable hits before the LLM reviewer runs.

Read more: [Analyzer catalog](ANALYZERS.md).

<span id="byok"></span>

### BYOK

**BYOK** (*bring your own key*) means you supply the model credential — a subscription
login or API key — and your code never leaves your GitHub Actions run or your machine.

Read more: [Installing mergeCraft](install.md).

<span id="sarif"></span>

### SARIF

**SARIF** is a standard JSON format for static-analysis results; mergeCraft can upload
analyzer output to GitHub code scanning when you opt in.

Read more: [Analyzer catalog — SARIF upload](ANALYZERS.md).

<span id="structural-approval-gate"></span>

### Structural approval gate

The **structural approval gate** is the `mergecraft-approval` check: its pass or fail is
computed only from typed findings and run state, not from free-form review prose.

Read more: [Terminal verdict vs structural verdict](../REVIEW-CHECKS.md#terminal-verdict-vs-structural-verdict-vp2).

<span id="learnings"></span>

### Learnings

**Learnings** are durable notes mergeCraft keeps in `.mergecraft/learnings.md` — for
example withdrawn false positives — so later reviews do not repeat the same mistake.

Read more: [Eval bank — learnings](eval-bank.md).

## See also

- [Landing README](../README.md) — links here on first use of each term
- [docs/workflows.md](workflows.md) — trust tiers and workflow examples
- [REVIEW-CHECKS.md](../REVIEW-CHECKS.md) — every check a review applies
