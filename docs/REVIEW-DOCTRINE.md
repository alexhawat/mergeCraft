# Review doctrine

Reasoning extracted from pullfrog-py history (`review_checks.py`, `review_taxonomy.py`,
`mcp/static_checks.py`, `REVIEW-CHECKS.md`) before the mergeCraft snapshot. W2 and W5
build on these decisions — they are not recoverable from code alone.

## Mechanical gates vs findings

**`unavailable` is not `failed`.** A gate whose executable is missing (no `make`, no
linter on PATH) says nothing about the diff. Reporting it as a failure invents a finding.
Only a real non-zero exit from an executable gate is evidence. The Action image ships
`git`, `gh`, `jq`, `node`, and `npm` — not `make` — so every Makefile-discovered target
lands as `unavailable` there unless the repo declares explicit `staticChecks` with binaries
that exist in the image.

## Makefile discovery, not tool inference

**`DISCOVERABLE_TARGETS` discovers Makefile targets, not tools.** The tuple
`("lint", "format-check", "typecheck", "ci-static")` is offered in order when no
`staticChecks` are declared. Nothing is inferred from file extensions; no interpreter or
linter is substituted. The repo's own gate is the only gate.

## Never substitute a toolchain version

When the repo has a tool, mergeCraft runs **the repo's copy** at **the repo's config and
version**. A reviewer carrying its own interpreter manufactures findings: `except A, B:`
is a `SyntaxError` under Python 3.13 and legal under 3.14 (PEP 758), which this project
requires. The module docstring, tool description, and mode prompt all encode this rule.

## Finding fingerprints

**`finding_fingerprint()` = `sha256(path + "\n" + casefolded whitespace-collapsed body)[:24]`.**
Whitespace and case are normalized so re-wrapping a comment does not change the hash, letting
a later run recognize a finding it already raised. The marker is stamped server-side in
`mcp/review.py`. **Cost:** paraphrases and minor rewordings produce new fingerprints; the
tradeoff favors stable dedup over semantic similarity.

## Output cap

**`MAX_OUTPUT_CHARS = 8_000`** caps combined stdout+stderr embedded in prompts. Raw tool output
beyond this truncates — a design constraint for W4's move to file-based parsing. Mechanical
gate output is evidence, not the finding itself.

## Subagent deny-list

**`subagent_denied_tool_names()` derives from every MCP tool with `mutates=True`.** If that
list is empty, startup **raises** — refusing to run a review subagent with the mutation gate
effectively disabled. The verification agent (W7) inherits the same guard.

## Verification covers every source, including ourselves (C6)

**A `Critical`/`Major` finding is a hypothesis until a second read-only agent has read the
cited code — whatever wrote it.** `should_verify()` was always severity-only; the source
condition lived in its two call sites (`analyzers/review_gate.py`, `ci/verification.py`), both
of which only ever fed it tool output. The effect was that the noisiest source — the reviewing
model's own findings — was the one source that never got checked. `verify_agent_findings` and
`record_finding_verdict` close that, on the same terms as the analyzer path: severity gate,
withdrawn-memory skip, and a dispatch cap.

**The cap is the inline budget, not a new knob.** Verification exists to protect what gets
published, so it can never cost more than publication does: dispatches are capped at
`analyzers.inlineBudget` and spent on `Critical` before `Major`. **Cost:** on a diff with more
than `inlineBudget` blocking findings, the overflow publishes unverified — the alternative
(unbounded judge dispatches on the worst diffs) is worse.

**A `drop` is durable.** It writes the verifier's reason under `WITHDRAWN_FINDINGS_HEADING` with
the finding's own fingerprint, so the same claim is skipped before verification on every later
run — the same section, parser and identity analyzer suppression already uses. Verifying a
finding the author refuted last month is the failure this prevents.

## Shell permission and static checks

**`run_static_checks` is withheld under `shell: disabled`.** Gates execute commands the repo
config names; on a pull request those are commands the PR author controls. Offline
`mergecraft diff-review` keeps the tool because config and tree belong to the operator.

## Provenance

Harvested from pullfrog-py `origin/main` commits `bff76e7` (feat/review-triage-and-mechanical-gates)
and `31441ce` (fix/static-check-availability-and-shell-gate), PR #20.

## Green is evidence, not proof (#41, W2)

A passing check-run is **evidence**, never a **proof**. The merge decision
is a function of durable, structured evidence — never of an agent's
self-report. Two consequences follow:

- **The agent's `approved` boolean is recorded but never sufficient.** It
  lives on the merge-evidence packet as `self_assessment` (with the
  reviewed `sha`) — a sibling of `decision`, not a substitute. When the
  agent's `self_assessment.approved == True` is the *only* positive
  signal, the verdict is `neutral` (or the packet's explicit `decision`
  if set upstream), not `auto_merge`. That is the #41 hard rule; it is
  pinned by `tests/evidence/test_self_assessment.py::test_self_assessment_alone_blocks_auto_merge`.
- **The decision is monotone in blockers.** Any `Critical` or `Major`
  finding yields `failure` regardless of the agent's `approved` value;
  `run_succeeded == False` yields `neutral`; `tier == "untrusted"`
  yields `neutral`. A "green" check-run never outvotes a blocker; an
  agent's `approved=True` never outvotes a blocker. See
  `mergecraft.agents.gates.decide_approval` (the security-trust-boundary
  plan's Batch D contract, D5) and `tests/status_checks/test_decide_approval.py`.

### Evidence weighting

What the merge-evidence packet carries, and how each signal weights:

| Signal | Weight | Notes |
|--------|--------|-------|
| `findings: list[Finding]` (typed, taxonomy-validated, `extra="forbid"`) | **structural** | One `Critical` or `Major` finding blocks. Source/severity/confidence preserved verbatim. |
| `deterministic_checks: list[DeterministicCheck]` (name, status, command) | **mechanical** | Only `passed` / `failed` count as positive / negative evidence; `unavailable` / `declared-but-cannot-run` / `timed_out` are honest skips — not silent passes (PR #17 vocabulary, see `REVIEW-CHECKS.md`). |
| `ci_check_runs` / `ci_intelligence.annotations` | **mechanical** | Per-ref check-suite outcome + log-cluster signatures, flaky vs stable, blame-attributed. |
| `self_assessment.approved: bool` + `self_assessment.sha` | **advisory only** | Recorded; never the sole positive input. The packet's `decision` row is authoritative. |
| `decision: { verdict, reason, decided_by }` | **authoritative** | Populated by `decide_approval`. When present on the packet, it wins over every other signal. |

What is **never** an input to the verdict: the agent's prose narrative,
the PR title / body / comment text (fenced), `result.output`, the model
slag in tool output, or any other string that was not produced by a
deterministic check on the diff. The merge-evidence packet is the
single artifact a human or a later tool reads to reconstruct why a PR
was auto-merged, blocked, or escalated; it is durable, versioned, and
the schema is derived from the Pydantic models (`mergecraft.evidence.
packet.PACKET_SCHEMA_VERSION`, D7).

### Honesty about unavailable signals (W2.4)

Where a signal source is unreachable, the packet records it as
`unavailable` with a reason — never silently as "passing". This is the
same honesty rule PR #17 landed for `staticChecks`: an environment
without `make`, a missing linter binary, an unreachable check-suite API,
or a CI provider mergeCraft cannot reach — all surface explicitly. The
"green" in a check-run summary is the verdict's input; "no signal" is a
verdict's input that says *the review has nothing to attest to*.

## Trust tiers and contributor weight

`analyzers/trust.py::derive_trust_tier()` collapses an event's metadata into one of
`trusted` (OWNER / MEMBER / COLLABORATOR on the base repo, or operator-owned payload
sources) or `untrusted` (fork PR head, `pull_request_target`, or anything with no
`author_association`). The fence's `tier=` and `trust=` headers carry this value forward
into the rendered prompt so a reviewer can weight what is inside the block.

How a reviewer should weigh that header on a per-field basis:

- **A `MEMBER` comment is not a finding.** It is context the reviewer reads *after* the
  diff — same as a first-time contributor's comment, with one extra signal: `MEMBER`
  comments have been pre-screened by the same gate that grants write access. They are
  more likely to describe a real concern, but they are still evidence, not instruction.
  A reviewer who reads a `MEMBER` comment and uses it to skip findings on a path is
  applying an instruction-shaped signal that the comment cannot carry — the diff is
  still the only thing that anchors a finding.
- **A first-time contributor's comment is read with no prior weight.** Treat it as
  *possibly* informed, *possibly* an injection probe. The fence's nonce binds the
  delimiters; a forged closer or opener cannot escape. If the comment's text tries to
  redirect the reviewer (skip this path, approve without reading, override your
  persona), the fenced block is exactly the place where the rule "evidence, not
  instruction" applies.
- **`OWNER` comments pass through unfenced** — see `fence_unless_trusted()` in
  `mergecraft.utils.fence`. The trust exemption is *per-field*, not per-thread:
  an OWNER-typed review comment does not extend trust to a sibling attacker's
  comment in the same thread. Each field's `author_association` is checked
  independently, and the W4 enumeration test pins that.

The hard rule (W4.5 / D9): **PR prose is evidence, never instruction.** A finding whose
only support is the PR title, PR body, or a comment is dropped or downgraded; the diff
must anchor every surviving finding. The fence is the technical mechanism that makes
this rule enforceable — without it, prose and instruction share a channel and a
sufficiently verbose injection can steer a review.

## Failure memory

The **eval bank** is mergeCraft's failure memory — the durable, file-backed case store
for failures a run should have caught and did not. The doctrine is **replay, not
re-execution.** A case captures a *failure mode*, not a *replay driver*. The replay
engine is a pure function of the case and the running code's verdict; the bank does not
re-run the agent, the analyzers, or the merge-evidence pipeline.

The bank surfaces two distinct failure modes:

- **`rejected`** — the reviewer said *no* before merge. The case asserts the packet
  should have produced a `block` verdict and the related finding.
- **`reverted`** — the merge made it past the reviewer but had to be rolled back. The
  case asserts the packet should have caught the regression that the revert exposed.

A failure mode is captured as a case by the operator, never by the agent. The
`create_pull_request_review` MCP tool logs a one-line suggestion at `logger.info` when
the run produced no positive findings on a re-review with trusted provenance and the
operator has opted in via the `suggest_eval_add` action input. The agent never
auto-adds — the bank is for *operator review*, not auto-capture.

The bank's promoted-tests workflow (`mergecraft eval promote <case-id>`) is the
regression net: a case promoted into `tests/evals/permanent/` re-runs the replay on
every CI. Drift surfaces as a failing pytest assertion alongside the rest of the suite.

The packet records the breadcrumb-and-summary of which bank cases the run attached to
its verdict via `MergeEvidencePacket.evals` (a typed `list[EvalMetadata]`; schema
`1.2.0`). The full case continues to live under `evals/cases/<case_id>.md`; the packet
row is the operator-facing reference.

The cross-reference is **one-way**: the doctrine refers to the bank, the bank refers
back to the doctrine. The bank does not embed doctrine; the doctrine does not embed
case payloads. The protocol is the join key (`case_id`).

## Provenance

(Harvested from pullfrog-py commits; see the heading above for sources.)
