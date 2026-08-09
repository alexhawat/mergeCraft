# The Merge Evidence Packet

Every mergeCraft run **that reviews a pull request** emits one **versioned,
structured packet** recording the durable evidence behind the merge decision.
The packet is the single artifact a human or a later tool reads to reconstruct
why a PR was auto-merged, blocked, or escalated — and it is **durable**,
meaning it survives the run and can be re-validated later.

A run with no pull request to attest to (an issue comment, a scheduled job)
emits nothing rather than a packet with an invented `change_id`.

## Where the packet lands

The emitter writes to the first of these that is set:

| Destination | When |
|---|---|
| `$MERGECRAFT_EVIDENCE_DIR` | An operator sets it explicitly. |
| `$RUNNER_TEMP/mergecraft/` | Default under GitHub Actions. |
| the run's temp directory | Local / offline runs. |

The filename is `<change-slug>-merge-evidence-packet.json`. `RUNNER_TEMP` is
deliberate on both counts: it survives the step, so a later
`actions/upload-artifact` can publish it, and it sits **outside** the
checkout, so an agent running `git add -A` can never sweep the packet into a
commit.

The Action exposes the resolved path as its **`evidence_packet` output**, and
logs it. A workflow attaches it like this:

```yaml
- id: review
  uses: alexhawat/mergeCraft@pre-0.0.1
  with:
    prompt: /review

- name: Upload merge evidence packet
  if: steps.review.outputs.evidence_packet != ''
  uses: actions/upload-artifact@v4
  with:
    name: merge-evidence-packet
    path: ${{ steps.review.outputs.evidence_packet }}
```

Locally, `mergecraft diff-review --evidence-packet PATH` writes the packet for
an offline review; without the flag it lands in the run's temp directory and
the path is logged.

This document is the normative field reference. The schema is the
contract; the prose below explains the contract field-by-field, with a
worked example at the end.

## Source

The packet is defined in `src/mergecraft/evidence/packet.py` and exposed
via `mergecraft.evidence.packet_output_schema()`. The JSON Schema is
**derived from the Pydantic models** — there is no hand-written schema
dict in parallel (D3). The precedent is
`mergecraft.analyzers.finding.findings_output_schema()`
(`src/mergecraft/analyzers/finding.py:138`).

## Versioning (D7)

The packet is versioned from day one. The version is asserted in a test
(`test_packet_schema_version_is_pinned`), and the literal lives at
`mergecraft.evidence.packet.PACKET_SCHEMA_VERSION`.

**Version bump rule.** Any field-level change (additive or otherwise)
that is not accompanied by a bump of `PACKET_SCHEMA_VERSION` must fail
the pinning test at the gate. Bumping the literal is the **only** way
to ship a schema change. The rules are:

1. **Additive changes** (new optional field, new nullable-until-later
   section, new value within an enum) require a `minor` bump and an
   entry in `## [Unreleased]` of [`CHANGELOG.md`](../CHANGELOG.md).
2. **Removing or renaming a field** requires a `major` bump and is
   treated as a breaking change — the versioned packet is no longer
   wire-compatible with the previous one.
3. **Schema-only documentation changes** (clarifying a docstring, fixing
   a typo) do **not** require a bump. The version is the contract, not
   the prose around it.

The current version is `1.3.0`.

Wiring a consumer is **not** a shape change: #96 gave these models their first
runtime caller without touching a single field, so `PACKET_SCHEMA_VERSION` did
not move.

### Version history

- `1.0.0` — initial schema (#47, W1). Required top-level fields, nullable
  `blast_radius` / `trajectory` / `evals` (D4), `Decision` row shape.
- `1.1.0` — W2 (#41). Adds the `self_assessment: SelfAssessment | None`
  section as a sibling of `decision`. Additive — the wire shape is
  backwards-compatible; the verdict function reads the new field but a
  packet with `decision=None` and no `self_assessment` validates as
  before. The legacy `ApprovalRecord.would_approve` surface stays for
  backward compatibility; the packet's `self_assessment` row is the
  explicit "what the agent *said*" record.

- `1.2.0` — W5 (#42). Replaces the nullable untyped `blast_radius`
  placeholder with `BlastRadiusClassification | None`. Populated packets now
  validate the lane, lane policy, reason, next action, and detected categories.
  The field remains optional, but its existing type changed, so D7 requires a
  minor bump.

- `1.3.0` — W12 (#44). Promotes the `evals` section from `dict[str, Any]` to
  `list[EvalMetadata] | None`. Additive — a packet that previously set `evals`
  to `None` continues to validate.

## Top-level fields

### `schema_version` — required

The pinned `PACKET_SCHEMA_VERSION` literal. Versioned at the top level
so downstream tooling can refuse packets whose schema version it does
not understand (D7).

### `change_id` — required

The fully-qualified PR identifier, in the form `owner/repo#123`. The
packet is the evidence *for* one PR; the `change_id` is its address.

### `agent` — required (`AgentMetadata`)

Identifies the producing agent. Shape:

| Field | Type | Notes |
|------|------|-------|
| `id` | `str` | The agent name (e.g. `claude`). |
| `version` | `str` | The agent's runtime version string. |
| `model` | `str` | The model slug the agent ran with. |

### `files_changed` — required (`list[str]`)

Repo-root-relative paths for every file touched by the PR. The packet
is the per-PR evidence record; this list is its scope.

### `findings` — required (`list[Finding]`)

The re-typed analyzer findings. The packet **composes** the existing
`Finding` model from `mergecraft.analyzers.finding`, not a parallel
finding model (D3). The wire shape is governed by the
[`Finding` schema](ANALYZERS.md); the packet's `findings` field
inlines that schema entirely into its emitted JSON Schema, so a
packet consumer never has to look at `$defs` to validate a
`findings` item.

### `deterministic_checks` — required (`list[DeterministicCheck]`)

The mechanical gates that ran (or were skipped) for this PR. Each
entry carries the check name, status, and the command that ran —
this is the **mechanical evidence** that backs the merge verdict.

| Field | Type | Notes |
|------|------|-------|
| `name` | `str` | The check name (e.g. `lint`). |
| `status` | `str` | The outcome (`pass` / `fail` / `skipped` / `unavailable`). |
| `command` | `str` | The literal command that ran. |

### `decision` — required (`Decision | None`)

The evidence verdict. W1 ships the **shape**; W2 (#41) populates this
field from `decide_approval()` (the function the security plan's Batch D
lands — D5). Until W2 the field is typically `{"verdict": "block",
"reason": "self-assessment-only run", "decided_by": "..."}`.

| Field | Type | Notes |
|------|------|-------|
| `verdict` | `str` | One of `auto_merge`, `block`, `request_changes`, `require_human_review`, `unavailable`, `neutral`. |
| `reason` | `str` | Human-readable explanation. |
| `decided_by` | `str` | Dotted path of the function that produced the verdict. |

### `self_assessment` — `SelfAssessment | None` (added in W2, #41)

The agent's recorded self-assessment — what it **said**. Distinct from
the `decision` row, which is what the evidence **proved**. The two
fields are populated independently: `self_assessment` carries the
agent's `approved` boolean + the reviewed commit SHA; `decision` carries
the structural verdict computed from typed findings + run state + trust
tier.

The `self_assessment` row is **advisory only**. When the packet carries
an explicit `decision` row, that row is returned verbatim by
`decide_approval(packet, …)` (#41 hard rule). When the packet does
**not** carry an explicit verdict and the recorded `self_assessment` is
the only positive signal, the verdict is `neutral`, never `auto_merge`.

| Field | Type | Notes |
|------|------|-------|
| `approved` | `bool` | The agent's `approved` boolean from `create_pull_request_review`. |
| `sha` | `str \| None` | The reviewed commit SHA. |

### `blast_radius` — `dict[str, Any] | None` (nullable until Batch B)

Placeholder; populated by Batch B's lane classifier. The field is
typed `| None` from W1 (D4) so the wire schema is fixed even though
the implementation lands later.

### `trajectory` — `dict[str, Any] | None` (nullable until Batch C)

Placeholder; populated by Batch C's `TrajectoryRecord` and the
trajectory auditor. Built from the MCP tool-call layer (D8) — no
external trace dependency.

### `evals` — `dict[str, Any] | None` (nullable until Batch E)

Placeholder; populated by Batch E's eval bank. The case store lives
under the existing `evals/` tree (D13).

## Worked example

A minimal but complete packet, showing the shape end-to-end. This is
also the canonical fixture used by the WA-T round-trip tests:

```json
{
  "schema_version": "1.1.0",
  "change_id": "alexhawat/mergeCraft#42",
  "agent": {
    "id": "claude",
    "version": "1.2.3",
    "model": "claude-sonnet-4-5"
  },
  "files_changed": ["src/mergecraft/evidence/packet.py"],
  "findings": [
    {
      "tool": "ruff",
      "rule_id": "F401",
      "category": "Maintainability & Code Quality",
      "severity": "Minor",
      "confidence": "likely",
      "message": "unused import",
      "path": "src/mergecraft/evidence/__init__.py",
      "start_line": 1,
      "end_line": 1,
      "fingerprint": "...",
      "evidence": [],
      "remediation": null,
      "autofix": null,
      "introduced_by_pr": "true",
      "source": "analyzer",
      "cluster_id": null
    }
  ],
  "deterministic_checks": [
    {
      "name": "lint",
      "status": "pass",
      "command": "ruff check src tests scripts"
    }
  ],
  "self_assessment": {
    "approved": false,
    "sha": "0123456789abcdef0123456789abcdef01234567"
  },
  "decision": {
    "verdict": "block",
    "reason": "self-assessment-only run",
    "decided_by": "mergecraft.agents.gates.decide_approval"
  },
  "blast_radius": null,
  "trajectory": null,
  "evals": null
}
```

`extra="forbid"` is enforced at the model level; any unknown
top-level field, or any unknown field on a nested model, is rejected
at validation. There is no second finding model: the packet's
`findings` items are exactly the [`Finding`](ANALYZERS.md) model
(D3).

## Reading the packet

The packet is the **contract** between the per-run evidence layer
and the gate layer. Consumers of the packet should:

1. Validate it against `mergecraft.evidence.packet_output_schema()`
   before reading any fields.
2. Treat the `schema_version` as a hard precondition — refuse
   versions your consumer does not understand.
3. **Never** rely on the agent's self-assessment alone (that is the
   `#41` rule; enforced by W2). The `decision` field is the
   evidence verdict.
4. Treat the packet as immutable. Downstream code that needs to
   annotate, score, or transform the packet should produce a new
   packet (with a new `schema_version` if the shape changes — D7).

## Where the packet is emitted

- **Schema & model:** `src/mergecraft/evidence/packet.py`
- **Pure assembly:** `src/mergecraft/evidence/build.py` (D3, convention 5)
- **I/O shell:** `src/mergecraft/evidence/emit.py` (W1.4)
- **Tests:** `tests/evidence/` (WA-T; W1.6 un-xfails the schema, round-trip, and sections)
- **Test plan:** `docs/test-plans/merge-evidence-gating.md`

## Cross-references

- D3 — the packet composes `Finding`; JSON Schema derived from the models.
- D7 — the packet is versioned from day one; the version is asserted in a test.
- D4 — nullable-until-later sections are typed `| None`, not omitted.
- D5 — `decision` is the W2 surface and consumes `decide_approval()`.
- D8 — `trajectory` is built from MCP tool state without external trace.
- D13 — `evals` is file-backed under `evals/`.
