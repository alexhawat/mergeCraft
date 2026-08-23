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
| `category` | `str` | yes | Failure category (e.g. `missed_finding`, `false_positive`, `multi_round_convergence`). |
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

The bank ships four subcommands under `mergecraft eval`. All four
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
mergecraft eval list --category rejected          # only rejected-pr cases
mergecraft eval list --category reverted          # only reverted-pr cases
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

### Multi-round convergence metric (RC6)

`mergecraft eval convergence` (and `make eval-convergence`) scores
first-pass recall and leakage rate from ledger snapshots — no live GitHub
calls. Inputs per round:

| Input | Role |
|-------|------|
| `ledger` | `FindingLedger` with lifecycle states per fingerprint |
| `findings` | Recorded finding rows (`path`, `start_line`, `end_line`, `body`, `fingerprint`) |
| `generated_fingerprints` | Every fingerprint the system produced in that round |
| `diff_text` | Round-one unified diff for attributing ground truth to the first reviewed SHA |

Ground truth is the fingerprint-deduped union of findings across all
rounds. First-pass recall is round-one open ∪ deferred findings divided
by ground truth attributable to round one (lines intersecting the round-one
diff). Leakage rate is round-one generated findings that never surfaced
(open or deferred), divided by round-one generated. Matching reuses
`evals/scoring.py` ±3-line overlap via `score_findings`, not fingerprint
equality. Results land in an optional `convergence` block on benchmark
result sets under `evals/results/`.

#### Multi-round case format (W10)

Cases with `category: multi_round_convergence` carry an ordered `rounds`
list in the YAML front matter. Each round records:

| Field | Role |
|-------|------|
| `round_index` | 1-based review round number |
| `diff_text` | Unified diff for attributing ground truth to round one |
| `findings` | Ground-truth rows (`fingerprint`, `path`, lines, `body`, `first_appeared_round`) |
| `ledger` | Ledger snapshot (`fingerprint`, `state`) for that round |
| `generated_fingerprints` | Every fingerprint the system produced in that round |

Single-round cases omit `rounds` entirely — the bank stays backward compatible.
`make eval-convergence` loads every `multi_round_convergence` case under
`evals/cases/` and folds corpus-wide first-pass recall and leakage rate.

#### Paired convergence gate (W10)

`mergecraft eval gate --baseline … --candidate …` compares
`convergence.mean_first_pass_recall` when both result sets include a
`convergence` block. A drop beyond the declared tolerance band fails the
release. The same comparison also runs the **DG1 precision corpus floor**:
`evaluate_dg1_precision_corpus()` must keep recall flat and
corpus-confirmed precision at or above
`PRE_DG1_BASELINE` — the paired constraint that blocks buying recall with
noise.

The replay diff has three statuses:

| Status | Meaning |
|--------|---------|
| `passed` | The current verdict matches the expected one. |
| `regression` | The current verdict differs from the expected one. |
| `blocked` | No current verdict was provided (the replay engine is unavailable). |

### `mergecraft eval promote <case-id>`

Promote a case into a permanent pytest test under `tests/evals/permanent/`:

```bash
mergecraft eval promote synthetic-001 \
  --target-dir tests/evals/permanent
```

The promoted test re-runs the case against the current code via
`mergecraft.evals.store.replay_case` and fails when the replay verdict
drifts from the case's recorded expected decision. The default replay
verdict is `None`, so a fresh promotion does not break the suite;
operators wire the running code's verdict via the
`MERGECRAFT_PERMANENT_CURRENT_DECISION` env var to surface drift.

The test self-contains the case payload (round-tripped through
`Case.model_validate_json`) so it carries no bank-disk dependency. The
function name is `test_permanent_<case_id>` and the file name is
`test_permanent_<case_id>.py`. Promoting twice without `--overwrite`
exits non-zero — the CLI refuses to clobber a committed test.

## Workflow: rejected & reverted PRs

The two most common failure modes that should never recur are **rejected**
PRs (a maintainer rejected the merge) and **reverted** PRs (the merge
shipped but was reverted). They are distinct failure modes in the bank:

- `rejected` — the reviewer said *no* before merge. The case asserts the
  packet should have produced a `block` verdict and the related finding.
- `reverted` — the merge made it past the reviewer but had to be rolled
  back. The case asserts the packet should have caught the regression
  that the revert exposed.

The bank surfaces both with first-class filters:

```bash
mergecraft eval list --category rejected   # only rejected-pr cases
mergecraft eval list --category reverted   # only reverted-pr cases
```

The `--category` filter is exact-match on the case's `category` field;
both values are accepted by the CLI's `--category` argument and the
canonical `CATEGORY_REJECTED` / `CATEGORY_REVERTED` literals are exported
from `mergecraft.evals.store` for downstream consumers.

### End-to-end: from a reverted PR to a permanent test

1. A revert PR is filed. The operator notices the bank has no case for
   that failure mode yet.
2. The operator hand-writes a case:

   ```bash
   mergecraft eval add \
     --id <short-sha> \
     --title "reverted: missed the regression on src/x.py" \
     --category reverted \
     --failure-mode <failure-mode> \
     --expected-finding "src/x.py:42: <the regression>" \
     --expected-decision block \
     --body "..."
   ```

3. The case is replayed to confirm it captures the failure:

   ```bash
   mergecraft eval replay <short-sha> --current-decision <whatever-the-running-code-says>
   ```

   The CLI exits `2` on a regression, `0` on pass, so a CI loop can
   latch on it.

4. The case is promoted into a permanent test that pytest will run on
   every CI:

   ```bash
   mergecraft eval promote <short-sha>
   ```

   The generated test embeds the case payload and re-runs the
   replay. The next CI run that drifts the verdict fails the
   permanent test alongside the rest of the suite.

5. The packet's `evals` section records the replay as a typed
   `EvalMetadata` row (schema `1.2.0`). The `MergeEvidencePacket.evals`
   list is the breadcrumb-and-summary of which bank cases the run
   attached to its verdict.

### Auto-prompt on re-review

The `create_pull_request_review` MCP tool logs a one-line suggestion at
`logger.info` when:

- The action input `suggest_eval_add` is `true` (default `false`).
- The trust tier is `trusted` (the suggestion is never surfaced on
  fork PRs or untrusted runs).
- The trigger is a re-review — not a fresh PR (fresh PRs do not yet
  produce a *rejected / reverted* failure mode).
- The run produced no positive findings.

The log line is informational. The agent never auto-adds. The eval bank
is for *operator review*, not auto-capture.

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
  render, list, replay, promote-to-permanent-test).
- `src/mergecraft/cli/eval_cmd.py` — the I/O shell (`add`, `list`,
  `replay`, `promote`).
- `src/mergecraft/evidence/packet.py` — the typed `EvalMetadata`
  breadcrumb on `MergeEvidencePacket.evals` (W12.2; schema `1.2.0`).
- `src/mergecraft/mcp/review.py` — the `create_pull_request_review` MCP
  tool + the `_maybe_suggest_eval_add` auto-prompt (W12.4).
- `tests/evals/test_store.py`, `tests/evals/test_replay.py`,
  `tests/evals/test_promote.py` — the pinned tests for the store,
  the replay diff, and the promote-to-permanent-test workflow.
- `tests/evidence/test_packet_evals.py` — the typed `EvalMetadata`
  packet tests.
- `tests/cli/test_eval_cmd.py` — the CLI tests (including the
  `--category=rejected` / `--category=reverted` filters).
- `docs/dev/test-plans/cross-file-deps.md` — the cross-file contract the
  bank inherits from the security Batch C plan.
- Issue [#44](https://github.com/alexhawat/mergeCraft/issues/44),
  Issue [#51](https://github.com/alexhawat/mergeCraft/issues/51).
