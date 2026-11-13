# Agent roster

One operator-facing surface for **which models each agent uses, in what order**,
**how many agents of each kind exist**, and **which of them run concurrently**.
The roster lives in `.mergecraft/config.yaml`; GitHub Actions auth wiring stays
in `.github/workflows/mergecraft.yml`.

```bash
mergecraft agent assign-model reviewer p0 opencode-go/deepseek-v4.1-flash  # register + roster + workflow (one command)
mergecraft agent assign-model reviewer p0 tokenhub/hy3       # exact slot, idempotent
mergecraft agent assign-model reviewer p1 openai/gpt-codex   # backup
mergecraft agent add-model    reviewer2 anthropic/claude-sonnet  # append, no index
mergecraft agent create       reviewer2 --role reviewer          # a second reviewer
mergecraft agent create       reviewer3 --role reviewer --after reviewer2
mergecraft agent-local assign-model reviewer p0 openai/gpt-codex  # local-only override
mergecraft workflow sync --check   # fail when roster models lack CI credentials
mergecraft provider status         # what CI will run — roster, credentials, wiring
mergecraft provider status --github   # also check repo secret presence
```

Full command reference: [`docs/cli.md`](cli.md).

## Two files, two jobs

| File | Owns |
|------|------|
| `.mergecraft/config.yaml` | Agent roster — names, roles, `modelChain` priority lists, `after:` dispatch order |
| `.github/workflows/mergecraft.yml` | Auth manifest — which providers CI can authenticate via `env: secrets.*` |

Naming a model whose provider has no credential step in the workflow is a **hard
error** at CLI write time and again at run start. Use
`mergecraft workflow sync --apply` to add the missing step, or
`--allow-unwired` on `agent assign-model` only when you intend to wire CI later.

## Priority slots (`pN`)

Priorities are `modelChain` list positions — **`pN` is a positional alias for
index N**, not a separate field.

| Command | Behaviour |
|---------|-----------|
| `agent assign-model <name> p0 <slug>` | Replace the primary model (idempotent on re-run) |
| `agent assign-model <name> p1 <slug>` | Replace or append at the next dense slot |
| `agent add-model <name> <slug>` | Append at the tail; no-op with a message when duplicate |
| `agent remove-model <name> <token>` | Remove by slot (`p1`) or slug; compacts the chain |

Slots are **dense**. Assigning `p3` on a two-long chain errors and names
the next assignable slot instead of writing a hole.

Within one agent, fallback on credential miss or retryable failure still walks
`modelChain` left to right — that is independent of multi-agent `after:`
ordering.

## Named agents

Agent names match `^[a-z][a-z0-9_-]{0,31}$`. Use `agent create` to add
bindings outside the closed `AgentRole` enum — for example a second reviewer:

```yaml
agents:
  reviewer:
    role: reviewer
    modelChain:
      - anthropic/claude-sonnet
  reviewer2:
    role: reviewer
    modelChain:
      - openai/gpt-5.3-codex
```

`agent delete` refuses to remove the last binding of a required role (`reviewer`,
`verifier`). `orchestrator` may never be duplicated.

`agent list` shows every binding, its `modelChain`, and the resolved dispatch
level. `agent show <name>` prints the effective model and limits for one agent.

## Local vs committed scope

| Surface | Writes | Read in CI? |
|---------|--------|-------------|
| `mergecraft agent …` | `.mergecraft/config.yaml` (committed) | Yes |
| `mergecraft agent-local …` | `.mergecraft/config.local.yaml` (gitignored) | **No** |

Local overrides merge over the committed file for CLI runs only. CI and the
GitHub Action read the committed roster from the run-scope settings snapshot.

`agent-local` skips the workflow auth-manifest check so you can experiment with
providers that are not wired into `mergecraft.yml` yet.

## Multi-reviewer execution

When more than one binding has `role: reviewer` and no `lens`, **all of them
run** on the same PR. Parallelism is in-process sub-agent dispatch — not one
GitHub Actions job per reviewer.

**Dispatch levels** come from `after:`:

- Omit `after:` → run in parallel with every other agent at the same level.
- `after: reviewer2` → run once `reviewer2` finishes.
- A failed dependency does **not** cancel dependents; the summary names which
  reviewer produced nothing.

**Findings merge** across reviewers by `(path, body, line)` — the same key
`ensemble` uses. Duplicate findings keep the **strictest severity**.

The server dispatches pending secondary reviewers after the primary finishes,
with peers in each level running concurrently. It waits for every peer's outcome
before starting the next level, including when a required reviewer fails.
Concurrent secondary reviewers must call `record_reviewer_dispatch_run` with
their own agent id and findings (an empty list for a clean review). A reviewer
that finishes without that record is reported as a dispatch error: findings in
shared tool state cannot prove which concurrent reviewer raised them.

**Attribution (`raised_by`).** Dispatch stamps `raised_by` server-side when
findings merge — agents cannot supply it on `submit_review_verdict`. Identical
findings from two reviewers list both agent ids; unknown provenance reads
`unknown`, never the primary reviewer. The field is display-only on the
published review and run record; it does not change verdict, severity, or dedup.

**Required reviewers (`review.rosterRequired`).** By default (`all`) every
configured reviewer is required: if any secondary reviewer fails, times out or
cannot be dispatched, the run is `inconclusive` (or `infra_error` when the
failure names an infrastructure reason such as an expired login), even when the
primary reviewer's verdict was accepted. Set `rosterRequired: marked` to require
only the reviewers whose entry sets `required: true`; a failure of any other
reviewer is recorded as a degradation note and the remaining reviewers still run.

```yaml
review:
  rosterRequired: marked     # all (default) | marked
agents:
  reviewer2:
    role: reviewer
    modelChain: [openai/gpt-5.3-codex]
    required: true           # read only under rosterRequired: marked
```

**Deadline.** Each secondary reviewer runs under its own budget — its
`timeoutS`, at most 900 s — not under whatever the primary reviewer left of the
run deadline, so a primary that used its whole deadline still leaves the second
provider a real run. Keep the job's `timeout-minutes` above the primary deadline
plus the secondaries' budgets.

**Secondary findings reach the review.** Findings a secondary reviewer or a file
group records after the primary submitted are merged into the run's verdict
before it is published: they appear as inline comments, and a blocking one turns
an `approve` into `request_changes`. `mergecraft review` adds them to `--json`
and to the exit code the same way.

**One verdict** is submitted by the orchestrator as today. Terminal-verdict
cardinality is unchanged: `mergecraft-approval` stays a single hardcoded check
name because there is only ever one submission.

### File-group fan-out (`review.fileGroupFanout`)

Off by default. On a large diff, mergeCraft can split the changed files into
bounded read-only groups and dispatch one reviewer per group server-side, after
the primary reviewer and before the secondary roster. Each group's prompt names
its own files and the shared diff path, and says that mergeCraft records the
group's outcome; it carries no roster submit block, and while a group runs the
`record_reviewer_dispatch_run` and `record_reviewer_dispatch_error` tools
refuse it, so a group can never stand in for the reviewer whose binding it
uses. A diff below both thresholds dispatches nothing.

**Which diff.** The selected mode determines the scope. `Review` fans out over
the full pull request diff even if checkout also produced an incremental diff.
`IncrementalReview` uses only the incremental diff — what changed since the
last review. If that diff is empty or its path is absent (including checkout's
`empty` and `unavailable` statuses), there is no fan-out even on a large pull
request; it never falls back to the full diff.

**Budget.** When the fan-out starts it takes `budgetShare` of the run budget
left (default half), and every group's cap counts against that slice, including
fractional seconds. Once the slice is exhausted, queued groups are recorded as
run-health failures without starting another reviewer. The secondary roster
does not draw on this budget: each secondary reviewer has its own deadline
(see **Deadline** above).

**What you can observe.** The groups run after the primary reviewer has
submitted and before the run publishes the review; their findings are merged
into the published review with the group named in their packet evidence. Group findings reach the evidence packet and the checks the way
secondary roster findings do. When mergeCraft records a group's run under
`file-group/<group-id>` (`group-1`, `group-2`, …), every finding row that group
raised gains one packet evidence entry `reviewer: file-group/<group-id>
(<model>)`. The entry survives re-verification: when a later group records the
same finding again, the row keeps the earlier group's entry exactly once. A group that fails — missing binding or credential, timeout,
provider error — is recorded as a reviewer dispatch error plus one run-scoped
`Minor` row under the packet's `run_health`; it never fails the review, and the
other groups' findings stand.

**Attribution and `concurrency`.** A row belongs to the group that recorded it.
mergeCraft knows that group when only one group is in flight, which is always
the case at the default `concurrency: 1`. With `concurrency` above 1, a
reviewer's tool calls over the MCP server do not say which group made them, so
rows are attributed in recording order: the first group whose run is recorded
after a row was stored claims it. Keep `concurrency: 1` when exact per-group
attribution matters.

```yaml
review:
  fileGroupFanout:
    enabled: true          # default false
    maxGroups: 6           # 1..12
    minFiles: 20           # fan out at >= 20 changed files ...
    minDiffLines: 800      # ... or at >= 800 added lines
    binding: reviewer2     # registry agent id; omit to reuse the primary reviewer
    concurrency: 1         # groups in flight, 1..6; 1 runs them one after another
    perGroupTimeoutS: 600  # 1..900; also capped by the binding's timeoutS and the fan-out budget
    budgetShare: 0.5       # share of the remaining run budget the whole fan-out may spend
```

| Key | Default | Meaning |
| --- | --- | --- |
| `enabled` | `false` | Turn the fan-out on. |
| `maxGroups` | `6` | Most groups per run (`1`–`12`). |
| `minFiles` | `20` | Changed-file count that triggers the fan-out on its own. |
| `minDiffLines` | `800` | Added-line count that triggers the fan-out on its own. |
| `binding` | _(primary reviewer)_ | Registry agent id whose model reviews every group. |
| `concurrency` | `1` | Groups in flight at once (`1`–`6`). |
| `perGroupTimeoutS` | `600` | Seconds per group (`1`–`900`), further capped by the binding's `timeoutS` and what is left of the fan-out budget. A binding `timeoutS: 0` is ignored; an exhausted fan-out budget prevents dispatch. |
| `budgetShare` | `0.5` | Share of the run budget left when the fan-out starts that the whole fan-out may spend (above `0`, at most `0.9`; no minimum duration). The secondary roster keeps the rest. |

Unknown keys under `fileGroupFanout` are rejected. Each group is a full
provider dispatch, so a fan-out of six groups costs roughly six extra reviewer
runs.

## Trust boundary

`.mergecraft/config.yaml` is PR-controlled after `checkout_pr`. The roster is
therefore read from the **run-start settings snapshot**, never from the
post-checkout tree.

At run start mergeCraft resolves `agents:` once, hashes `.mergecraft/config.yaml`,
and carries both immutably. Any later edit to the config file on disk is refused
(`assert_config_unchanged`). A PR-head change to `agents:` cannot change which
model reviews that PR.

Implementation: `src/mergecraft/config/settings_snapshot.py` (AG2 / MCB-19).
Roster helpers in `src/mergecraft/config/agent_roster.py` import the snapshot
primitives — do not duplicate snapshot logic elsewhere.

## Inspecting what CI will run

`mergecraft provider status` is the read-only inspection command for the
question *"what will CI actually run?"* It projects the committed roster onto
credential presence, workflow auth wiring, dispatch levels, and per-slot skip
reasons — without calling a model or mutating config.

```bash
mergecraft provider status              # offline view from config + workflow
mergecraft provider status --github     # also query repo secret presence
mergecraft provider status --json       # machine-readable output (schema v1)
```

| State | Meaning | Typical remedy |
|-------|---------|----------------|
| credential missing | env var absent locally (or secret absent with `--github`) | `mergecraft provider auth <label>` |
| not wired | provider absent from `mergecraft.yml` auth manifest | `mergecraft workflow sync --apply` |
| disabled | credentials cleared via `provider disable` | `mergecraft provider enable <label>` |

``--github`` needs a token with ``repo`` scope (``gh auth token`` or
``GITHUB_TOKEN``). Without one every remote field is ``unknown`` and the command
still exits 0. Secrets are reported as present/absent only — values are never
printed (#520).

``--cwd`` selects every target — config path, git resolution, workflow file,
and registry — the same rule as `provider disable` (#521).

## Workflow sync

`mergecraft workflow sync` projects the committed roster onto the workflow auth
manifest:

```bash
mergecraft workflow sync --check    # exit non-zero when a roster provider is unwired
mergecraft workflow sync --apply    # add missing review steps (owned keys only)
```

The workflow YAML is not the source of truth for per-agent models — it only
declares which providers CI can authenticate. Per-agent `modelChain` data stays
in config.

## Getting started

After `mergecraft init`, authenticate one provider — the first successful
`mergecraft provider auth <label>` seeds `agents.reviewer` p0 from that
provider's preferred model. No third command is required before
`mergecraft review` works. See [`docs/authentication.md`](authentication.md#quick-start--init--auth--review).

**See also:** [`docs/authentication.md`](authentication.md) · [`docs/workflows.md`](workflows.md) · [`docs/cli.md`](cli.md)
