# Agent roster

One operator-facing surface for **which models each agent uses, in what order**,
**how many agents of each kind exist**, and **which of them run concurrently**.
The roster lives in `.mergecraft/config.yaml`; GitHub Actions auth wiring stays
in `.github/workflows/mergecraft.yml` (D1).

```bash
mergecraft agent assign-model reviewer p0 nous/tencent/hy3   # exact slot, idempotent
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

## Two files, two jobs (D1)

| File | Owns |
|------|------|
| `.mergecraft/config.yaml` | Agent roster — names, roles, `modelChain` priority lists, `after:` dispatch order |
| `.github/workflows/mergecraft.yml` | Auth manifest — which providers CI can authenticate via `env: secrets.*` |

Naming a model whose provider has no credential step in the workflow is a **hard
error** at CLI write time and again at run start (D1a). Use
`mergecraft workflow sync --apply` to add the missing step, or
`--allow-unwired` on `agent assign-model` only when you intend to wire CI later.

## Priority slots (`pN`)

Priorities are `modelChain` list positions — **`pN` is a positional alias for
index N**, not a separate field (D3).

| Command | Behaviour |
|---------|-----------|
| `agent assign-model <name> p0 <slug>` | Replace the primary model (idempotent on re-run, D4) |
| `agent assign-model <name> p1 <slug>` | Replace or append at the next dense slot |
| `agent add-model <name> <slug>` | Append at the tail; no-op with a message when duplicate (D4) |
| `agent remove-model <name> <token>` | Remove by slot (`p1`) or slug; compacts the chain |

Slots are **dense** (D5). Assigning `p3` on a two-long chain errors and names
the next assignable slot instead of writing a hole.

Within one agent, fallback on credential miss or retryable failure still walks
`modelChain` left to right — that is independent of multi-agent `after:`
ordering (D15).

## Named agents

Agent names match `^[a-z][a-z0-9_-]{0,31}$` (D11). Use `agent create` to add
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
`verifier`, D12). `orchestrator` may never be duplicated (D7 cardinality).

`agent list` shows every binding, its `modelChain`, and the resolved dispatch
level. `agent show <name>` prints the effective model and limits for one agent.

## Local vs committed scope (D2)

| Surface | Writes | Read in CI? |
|---------|--------|-------------|
| `mergecraft agent …` | `.mergecraft/config.yaml` (committed) | Yes |
| `mergecraft agent-local …` | `.mergecraft/config.local.yaml` (gitignored) | **No** |

Local overrides merge over the committed file for CLI runs only. CI and the
GitHub Action read the committed roster from the run-scope settings snapshot.

`agent-local` skips the workflow auth-manifest check so you can experiment with
providers that are not wired into `mergecraft.yml` yet.

## Multi-reviewer execution (D6, D7, D15, D16)

When more than one binding has `role: reviewer` and no `lens`, **all of them
run** on the same PR. Parallelism is in-process sub-agent dispatch — not one
GitHub Actions job per reviewer (D16).

**Dispatch levels** come from `after:` (D15):

- Omit `after:` → run in parallel with every other agent at the same level.
- `after: reviewer2` → run once `reviewer2` finishes.
- A failed dependency does **not** cancel dependents; the summary names which
  reviewer produced nothing.

**Findings merge** across reviewers by `(path, body, line)` — the same key
`ensemble` uses (D6). Duplicate findings keep the **strictest severity**.

**One verdict** is submitted by the orchestrator as today (D7). Terminal-verdict
cardinality is unchanged: `mergecraft-approval` stays a single hardcoded check
name because there is only ever one submission.

## Trust boundary (D9)

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
printed (#520 / D11).

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
provider's preferred model (D10). No third command is required before
`mergecraft review` works. See [`docs/authentication.md`](authentication.md#quick-start-init--auth--review).

**See also:** [`docs/authentication.md`](authentication.md) · [`docs/workflows.md`](workflows.md) · [`docs/cli.md`](cli.md)
