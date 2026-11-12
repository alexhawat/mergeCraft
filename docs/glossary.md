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

Read more: [docs/REVIEW-CHECKS.md](REVIEW-CHECKS.md) — how findings are graded and gated.

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

Read more: [Terminal verdict vs structural verdict](REVIEW-CHECKS.md#terminal-verdict-vs-structural-verdict-vp2).

<span id="learnings"></span>

### Learnings

**Learnings** are durable notes mergeCraft keeps in `.mergecraft/learnings.md` — for
example withdrawn false positives — so later reviews do not repeat the same mistake.

Read more: [Eval bank — learnings](eval-bank.md).

<span id="jev"></span>

### Jev

**Jev** is an optional screening gate that ranks and filters the changed code units
before the generative reviewer reads them. It is advisory (shadow-only) today and never
replaces the reviewer. Each Jev question is a call to TypeSafe's hosted service, so
enabling it sends review content to TypeSafe; it is off unless you set `jev.enabled`.

Read more: [Jev gate patterns](jev-gate-patterns.md),
[Data sent to TypeSafe](jev-gate-patterns.md#data-sent-to-typesafe).

<span id="roster"></span>

### Roster

The **roster** is the list of reviewer agents in `.mergecraft/config.yaml` and the
ordered model chain each one uses (`agents.reviewer`, with `p0` as the first slot and
later slots as backups). The workflow file separately says which providers CI can
authenticate with.

Read more: [Agent roster](agent-roster.md).

<span id="lens"></span>

### Lens

A **lens** is a focused review rubric — security, concurrency, API compatibility, data
integrity and others — that the reviewer applies to the parts of a change it fits.
`mergecraft lens list` shows the bundled set.

Read more: [REVIEW-CHECKS](REVIEW-CHECKS.md).

<span id="lane"></span>

### Lane

A **lane** is the blast-radius class a change lands in: `low` (eligible for auto-merge
once required checks pass), `medium` (assisted review) or `high` (automatic merge is
forbidden). The lane is a signal in the evidence packet, not an instruction to merge.

Read more: [Blast-radius classifier](blast-radius.md),
[Blast-radius merge lanes](REVIEW-CHECKS.md#blast-radius-merge-lanes).

<span id="receipts"></span>

### Receipts

A **receipt** (fail-then-pass receipt) is a small JSON file your own CI uploads to show
that a test failed on the base commit and passes on the head commit. A pull request
that calls itself a fix needs one; mergeCraft reads it but never runs your tests.

Read more: [Fail-then-pass receipts](red-green-receipts.md).

<span id="evidence-packet"></span>

### Evidence packet

The **evidence packet** is the versioned, structured record a run writes for each pull
request it reviews: findings, deterministic checks, the blast-radius lane and what was
read. It lets a person or a later tool reconstruct why a change was blocked or allowed.

Read more: [The Merge Evidence Packet](evidence-packet.md).

<span id="terminal-verdict"></span>

### Terminal verdict

The **terminal verdict** is the `approve` or `request_changes` choice the reviewing
agent records through the typed `submit_review_verdict` tool. A run without one is
`inconclusive`, however fluent its prose. It is distinct from the structural verdict,
which is computed from typed findings.

Read more: [Terminal verdict vs structural verdict](REVIEW-CHECKS.md#terminal-verdict-vs-structural-verdict-vp2).

<span id="checks"></span>

### `mergecraft` and `mergecraft-approval` checks

Two GitHub checks appear on a reviewed pull request. **`mergecraft`** reports how the
run ended (passed, failed, inconclusive, timed out and so on). **`mergecraft-approval`**
is the [structural approval gate](#structural-approval-gate): it passes or fails from
typed findings and run state alone.

Read more: [REVIEW-CHECKS](REVIEW-CHECKS.md), [Troubleshooting](troubleshooting.md).

## See also

- [Landing README](../README.md) — links here on first use of each term
- [docs/workflows.md](workflows.md) — trust tiers and workflow examples
- [docs/REVIEW-CHECKS.md](REVIEW-CHECKS.md) — every check a review applies
- [Troubleshooting](troubleshooting.md) · [Cost](cost.md) · [Architecture](architecture.md)
