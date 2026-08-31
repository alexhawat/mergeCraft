# Operator trust policy — two axes, three levels

mergeCraft separates **what may run** against a checkout from **what the
agent's own output may unlock**. The operator knob `trust.selfReview` adjusts
the first axis for same-repo `pull_request_target` runs only. It does **not**
replace the structural approval lane in `mergecraft-approve.yml`.

**Audience:** consumer (operators wiring self-review on their own repository)

## Why two axes (D13)

| Axis | Question | Typical consumer |
|------|----------|------------------|
| **Execution trust** | May trusted-tier analyzers and repo-executable config run against this checkout? | Analyzer provisioning, sandbox posture |
| **Authority trust** | May the agent's own terminal output unlock approval semantics on this run? | `create_pull_request_review`, gate-facing verdict tools |

Before plan 13, both questions were conflated in a single `trust_tier` from
`derive_trust_tier()`. That function's `pull_request_target → untrusted`
return **still applies to authority** unless the operator explicitly opts into
`full`. Execution trust is derived beside it — never by editing that return.

Read more: [`src/mergecraft/config/trust_policy.py`](../../src/mergecraft/config/trust_policy.py),
[`src/mergecraft/analyzers/trust.py`](../../src/mergecraft/analyzers/trust.py).

## Three levels (`trust.selfReview`)

Configured in `.mergecraft/config.yaml` (default when absent: `off`).

```yaml
trust:
  selfReview: "off"   # quote — YAML 1.1 coerces bare off/on to booleans
  agentSandbox: "dispatch"  # lane B / #553 — see agentSandbox ladder below
```

Valid levels: `off`, `analyzers`, `full` (default when absent: `off`).

| Level | Execution trust (same-repo `pull_request_target`) | Authority trust | Real GitHub APPROVE |
|-------|--------------------------------------------------|-----------------|---------------------|
| `off` | Untrusted (today's default) | Untrusted | Only via `mergecraft-approve.yml` when the structural check passes |
| `analyzers` | Trusted — trusted-tier analyzers may run | Untrusted — agent cannot APPROVE | Only via `mergecraft-approve.yml` |
| `full` | Trusted | Trusted — agent may unlock approval semantics on this run | Agent path **or** `mergecraft-approve.yml` |

**Fork PRs are unaffected at every level** — both axes stay untrusted regardless
of `selfReview`.

## `trust.agentSandbox` — Codex sandbox override ladder (#553)

The Action input `codex_sandbox` (env `MERGECRAFT_CODEX_SANDBOX`) is a **request**
to skip Codex's nested bubblewrap/Landlock sandbox. Whether that request is
honoured is decided by `trust.agentSandbox` in the **base snapshot** at run
start — the same snapshot rule as `selfReview` (D1d). A PR-head edit cannot
raise its own tier mid-run.

Valid tiers (tightest first): `never`, `merged-only`, `dispatch` (default),
`same-repo`.

| Tier | Grants `danger-full-access` when… |
|------|-----------------------------------|
| `never` | Never |
| `merged-only` | Bound head SHA is an ancestor of `origin/<default-branch>` (after fetch) |
| `dispatch` | `workflow_dispatch` on a non-fork head |
| `same-repo` | Any non-fork head (`workflow_dispatch`, `pull_request`, `pull_request_target`) |

**Fork floor (hard):** a fork head refuses in **every** tier. No config value,
Action input, or event name reaches it. This is the amended #553 boundary:
the override cannot take effect on a fork head (not merely on
`pull_request_target` — same-repo `pull_request_target` may grant at
`same-repo`).

**`merged-only` caveat (D1e):** an open PR's head is not yet on the default
branch, so this tier does **not** give a working shell during PR review. It
exists for scheduled audits and post-merge sweeps on the default branch. "On the
default branch" only implies "reviewed" where merging requires review (for
example branch protection with required checks) — it is not a substitute for
your merge policy.

**Residual risks** (documented in the scaffolded config comment):

- A fork PR checked out onto a local branch looks like a same-repo head.
- Adding a collaborator widens `same-repo` to anyone with write access.

Inspect and configure:

```bash
mergecraft trust show
mergecraft trust set-agent-sandbox dispatch
mergecraft trust set-agent-sandbox same-repo --i-understand-same-repo-sandbox
```

Upgrade the pinned Action image **before** writing `agentSandbox` in config —
`TrustSettings` is `extra="forbid"`, so an unknown key against an older pin
fails the whole config load (D1f).

Run manifest fields (`agent_sandbox_tier`, `agent_sandbox_honoured`, …) land in
the evidence packet alongside the `trust_*` keys.

### Why `full` is not the default

`pull_request_target` runs read PR-authored content as part of reviewing it.
The agent's own `approved: true` narrative cannot be the thing that unlocks a
real merge approval on that trigger — that is the lesson of PR #200 and the
D14 separation. Default `off` preserves today's posture byte-for-byte.

`full` is an explicit operator opt-out of that separation for **their own**
repository. It requires:

- `mergecraft trust set-self-review full --i-understand-this-grants-approval-authority`
- A warning at CLI write time and at run start (`trust_policy.py`)

It must not appear as the happy-path recommendation in consumer docs.

## Why `mergecraft-approve.yml` exists

The APPROVE half of self-review is **already solved** without widening agent
authority:

- Trigger: `workflow_run` after `mergecraft` completes — definition always
  from the default branch, no PR checkout on the approving runner.
- Input: the `mergecraft-approval` check conclusion mergeCraft already posted —
  a pure function of finding severities (`decide_approval`), not agent prose.
- Output: PAT-backed APPROVE only when that conclusion is `success`.

The reviewing workflow (`mergecraft.yml`) stays on `pull_request_target` only.
Do not re-add a `pull_request` trigger to earn "trusted" tier — PR #200 reverted
that same day because it hands credentials to PR-controlled workflow definitions.

Read more: [`.github/workflows/mergecraft-approve.yml`](../../.github/workflows/mergecraft-approve.yml),
[Security model — structural approval](workflows.md#security-model).

## Base-snapshot rule (D15)

The effective trust policy is resolved **once at run start from the base tree**
— the same snapshot that supplies `.mergecraft/config.yaml` on
`pull_request_target` (default-branch workflow definition + default-branch
config). A PR that edits `trust.selfReview` on its own branch **cannot raise
its own tier** during that run.

Implementation:

- Lane C / MCB-19 `RepoSettingsSnapshot` carries `config_hash` at snapshot time.
- `resolve_trust_policy()` reads `trust.selfReview` only from that snapshot.
- A mismatch during the run fails closed (same primitive as other snapshot guards).

Inspect the live posture:

```bash
mergecraft trust show              # effective policy + resolution source + hash
mergecraft trust set-self-review analyzers   # writes committed config
```

`--cwd` selects every target — both the `.mergecraft/` path and git resolution
(see PR #521).

Run manifest fields (`trust_self_review`, `trust_execution`, `trust_authority`,
`trust_resolved_from`, `trust_config_hash`) land in the evidence packet so
readers of a review can see the posture it was produced under.

## Related pages

- [Workflows — security model](workflows.md#security-model)
- [Threat model — trust knob boundary](THREAT-MODEL.md#operator-trust-knob)
- [CLI — `mergecraft trust`](cli.md)
- [Glossary — trust tier](glossary.md#trust-tier)
