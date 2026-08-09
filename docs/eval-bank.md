# The Failure Memory and Eval Bank

The eval bank is mergeCraft's **durable, file-backed case store** for
the failures a run should have caught (and did not). Each case is a
markdown file with a YAML front matter that gets validated against the
locked `LearningProvenance` record from the security Batch C plan.

The bank is **local** (D13). There is no database, no hosted service,
no sync. The bank lives under `evals/cases/` in the repo, and the CLI
walks the directory directly. The CLI is the only I/O surface.

This document is the user-facing manual for the bank. The schema and
the cross-file contract are normative; the CLI reference is descriptive.

## Why a file-backed store?

A few run-time failures keep recurring — a missed finding pattern, a
rejected verdict, a reverted PR. Capturing each one as a **case**
means the next run can replay it and the structural rule the case
asserts is regression-tested against the running code. Cases are
narratively rich (the operator wrote what happened) and structurally
strict (the front matter is validated by Pydantic).

The bank is local for the same reason mergeCraft is BYOK-local: there
is no hosted service to host it on. The repo carries the bank; the
audit tooling walks it.

## Schema

### File layout

Each case is a single markdown file under `evals/cases/` with the
case id as the file stem:

```
evals/cases/
  synthetic-001.md
  synthetic-002.md
  ...
```

The file's body is a markdown document with a YAML front matter. The
front matter is the **metadata**; the body is the **description**.

### Front matter

The front matter is validated against `LearningProvenance` (D5). The
record is the same one the security Batch C plan pinned, so the audit
tooling can grep on a stable shape:

| Field | Type | Required | Notes |
|------|------|----------|-------|
| `id` | `str` | yes | Stable identifier. Must match `^[A-Za-z0-9][A-Za-z0-9._\-]{0,127}$`. The CLI rejects IDs outside this shape. |
| `title` | `str` | yes | Short, operator-readable description. |
| `category` | `str` | yes | Failure category (e.g. `missed_finding`, `false_positive`). |
| `submitted_at` | `datetime` | yes | ISO-8601 UTC timestamp. The CLI writes this on `add`. |
| `run_id` | `str` | yes | The run id the case came from. |
| `pr_number` | `int \| None` | no | Optional PR number. |
| `failure_mode` | `str` | yes | What went wrong (e.g. `missed_finding`, `ignored_tool_error`). |
| `expected_finding` | `str` | yes | The finding the packet should have produced (path:line or text). |
| `expected_decision` | `str` | yes | The verdict the packet should have produced. One of `auto_merge`, `block`, `request_changes`, `require_human_review`, `unavailable`, `neutral`. |
| `replay_command` | `str` | yes | The CLI invocation to replay the case. |
| `provenance` | `LearningProvenance` | yes | The provenance record — see below. |

The `extra="forbid"` invariant on `LearningProvenance` is the
guarantee that the case's metadata cannot silently drift from the
security plan's contract. The store imports the type from
`mergecraft.utils.learnings` and uses it as-is.

### `provenance` (D5)

The provenance record is the same shape the security Batch C plan
ships for the learnings file:

| Field | Type | Notes |
|------|------|-------|
| `run_id` | `str` | The run id (non-empty). |
| `pr_number` | `int \| None` | PR number, or `None` for non-PR runs. |
| `source_field` | `str` | The field the entry was derived from. The bank uses `eval_bank`. |
| `author_login` | `str` | GitHub login of the author. |
| `author_association` | `str \| None` | `OWNER`, `MEMBER`, `COLLABORATOR`, `NONE`, `CONTRIBUTOR`, etc. |
| `trust_tier` | `Literal["trusted", "untrusted"]` | From `analyzers.trust.derive_trust_tier`. |
| `timestamp` | `datetime` | ISO-8601 UTC. |

### Example

```yaml
---
id: synthetic-001
title: PR review missed a fabricated deletion
category: missed_finding
submitted_at: 2026-08-09T10:00:00Z
run_id: synthetic
pr_number: 1
failure_mode: missed_finding
expected_finding: "src/mergecraft/foo.py:42-60: 'delete' on unborn file"
expected_decision: block
replay_command: "mergecraft eval replay synthetic-001"
provenance:
  run_id: synthetic
  pr_number: 1
  source_field: eval_bank
  author_login: synthetic
  author_association: OWNER
  trust_tier: trusted
  timestamp: 2026-08-09T10:00:00Z
---

# synthetic-001

The agent reviewed a PR that asked the tooling to delete a path that
did not exist in the repo. The packet should have produced a `Finding`
flagging the unborn-file deletion, and the verdict should have been
`block`.

## Expected finding

The packet should carry a `Finding` with `category: correctness`,
`severity: Major`, `path: src/mergecraft/foo.py`, `start_line: 42`,
`end_line: 60`.

## Expected decision

The verdict should be `block` because the operation is structurally
invalid — there is no file at that path to delete.
```

## CLI

The bank ships three subcommands under `mergecraft eval`. All three
operate on the default `evals/cases/` directory; pass `--bank` to
override.

### `mergecraft eval add`

Add a case from the CLI. The flags map to the front-matter fields
one-to-one:

```bash
mergecraft eval add \
  --id synthetic-001 \
  --title "missed a fabricated deletion" \
  --category missed_finding \
  --failure-mode missed_finding \
  --expected-finding "src/mergecraft/foo.py:42-60: 'delete' on unborn file" \
  --expected-decision block \
  --run-id synthetic \
  --pr-number 1 \
  --author synthetic \
  --trust-tier trusted \
  --body "# synthetic-001

The agent reviewed a PR that ..."
```

The CLI is **non-interactive**. Every field is a flag, so the add
flow is automatable and easy to script. The case is validated against
the schema before being written; the CLI exits non-zero on a
validation failure.

### `mergecraft eval list`

List cases in the bank. Optional filters:

```bash
mergecraft eval list                              # every case
mergecraft eval list --category missed_finding    # only missed findings
mergecraft eval list --since 2026-08-01           # submitted since
mergecraft eval list --id-prefix synthetic        # synthetic test fixtures
mergecraft eval list --json                       # JSON output
```

The listing is sorted by `submitted_at` ascending. The JSON output
mirrors the case schema one-to-one and is suitable for audit-log
pipelines.

### `mergecraft eval replay`

Replay a case and report the diff against the recorded expected
decision:

```bash
mergecraft eval replay synthetic-001 \
  --current-decision block \
  --json
```

The replay function is **pure**. The CLI does not invoke the agent or
the merge-evidence pipeline — the caller supplies the running code's
current verdict and the diff is computed deterministically. The CLI
exits with status `2` when the diff is a regression, so a CI loop can
latch on the regression and fail the run.

The diff has three statuses:

| Status | Meaning |
|--------|---------|
| `passed` | The current verdict matches the expected one. |
| `regression` | The current verdict differs from the expected one. |
| `blocked` | No current verdict was provided (the replay engine is unavailable). |

## Governance rules

The wave plan pins the following rules (D5, D13, D11):

1. **Local + file-backed.** No database, no hosted service. Cases
   live under `evals/cases/`. The merge-evidence **packet does not
   auto-merge** (D11); the eval bank is for *reviewer learning*, not
   auto-merge. The replay output is a structured diff, not a merge
   action.
2. **Provenance is mandatory.** Every case carries a
   `LearningProvenance` record validated by the security plan's
   model. A case without a provenance record is rejected at write
   time.
3. **`extra="forbid"`** is the invariant on the provenance model.
   The bank does not redefine the record; it embeds the one the
   security plan ships.
4. **Synthetic cases for tests.** The test suite mutates fixtures
   with the `synthetic` prefix; the committed corpus never looks
   like a real historical failure record. Operators can use any
   prefix in production.
5. **Replay is deterministic.** The replay function is a pure
   function of the case and the current verdict. The CLI does not
   invoke the agent; the caller supplies the verdict.

## Source

- `src/mergecraft/evals/store.py` — the pure core (schema, parse,
  render, list, replay).
- `src/mergecraft/cli/eval_cmd.py` — the I/O shell (`add`, `list`,
  `replay`).
- `tests/evals/test_store.py`, `tests/evals/test_replay.py` — the
  pinned tests for the store and the replay diff.
- `tests/cli/test_eval_cmd.py` — the CLI tests.
- `docs/test-plans/cross-file-deps.md` — the cross-file contract the
  bank inherits from the security Batch C plan.
- Issue [#51](https://github.com/alexhawat/mergeCraft/issues/51).
