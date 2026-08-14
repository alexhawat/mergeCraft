# Config-failure policy (D4)

mergeCraft splits configuration errors into two classes. The split is
enforced in code (`src/mergecraft/config/settings.py`, `src/mergecraft/main.py`)
and pinned by conformance tests under `tests/config/`.

## Hard-fail — security / runtime surfaces

Errors on **security and runtime** settings fail closed as
`RunOutcome.configuration_error` (or a `ValidationError` that aborts
config load before the run starts). A typo must never silently widen
permissions or leave the runner in an ambiguous state.

Surfaces in this class (Pydantic `extra="forbid"`):

| Model | Why |
|-------|-----|
| `RepoSettings` | `push` / `shell` / scripts / model chain — the run's capability envelope |
| `GatesSettings` | Gate mode / override vocabulary |
| `AnalyzersSettings` | Analyzer enablement and trust-adjacent toggles |
| `TracingSettings` | Whether reviewed-repo content may leave the runner |
| Optional-feature blocks (`StaticCheckDefinition`, `CiEvidenceSettings`, `ModeDefinition`, `TraceSinkEntry`) | **Flipped to `forbid` at pre-0.0.1 (D8).** The one-release warning shim has ended — an unknown key now fails closed the same way the security/runtime blocks do, so a typo on a `staticChecks` / `ciEvidence` / `modes` / `tracing.sinks` entry aborts instead of silently dropping |

Invalid enum values on `push` / `shell`, unknown keys on those models, and
unparseable Action inputs that drive runtime (`timeout`) all fail closed.
`allowFallback: false` with an unavailable primary model also fails closed
as `configuration_error` (W10 / #20) rather than silently reviewing under a
backup slug.

## Warn-and-disable — optional features

Errors on **optional-feature** surfaces warn and disable (or fall back)
that feature only. They must never abort a review that would otherwise
run.

Examples:

| Surface | Behaviour |
|---------|-----------|
| Syntactically broken `.mergecraft/config.yaml` | Warn, fall back to `default_settings()` (D9 — broken YAML is **not** fail-closed) |
| Learnings seed / bundled-skills install failure | Warn and continue without that feature |

> Trusted-tier `setupScript` failures are **not** in this table: see the
> dedicated section below — S1 changed the default from warn-only to
> `inconclusive`.

Review-relevant **prep / dependency-install** failure is a third shape: the
run maps to `RunOutcome.inconclusive` with the install reason recorded
(not `passed`, not a silent continue). That is fail-closed for the
*outcome*, not a hard abort before the agent starts.

## Setup-script failures (S1 / D5 / D10 / F6)

A trusted-tier `setupScript` failure (non-zero exit or timeout) used to be
warn-only. **S1 changes that default**: a failed or timed-out setup script
now maps the run to `RunOutcome.inconclusive` (D5) — an under-provisioned
tree never receives a review verdict. Operators can opt into a different
shape via the `setup_failure_policy` Action input:

| Policy          | Effect on a trusted-tier setup failure (non-zero exit **or** timeout) |
|-----------------|----------------------------------------------------------------------|
| `inconclusive` (default) | Run → `RunOutcome.inconclusive` (neutral check conclusion). The agent still runs under the WARN semantic when a failure happens with this policy? **No** — see below. |
| `fail`          | Run → `RunOutcome.configuration_error`. The consumer has declared the failure is unrecoverable; the run aborts. |
| `warn`          | Today's behaviour: the run continues (`passed`), but the agent prompt still carries the failure text so the reviewing model knows its tree may be partially provisioned. |

**What `inconclusive` actually means for the WARN legacy:** with the
default policy, a setup failure aborts the review verdict — the run is
neither a clean `passed` nor a `failed` review, but a `neutral` check
conclusion. To get today's continue-on-failure behaviour back, explicitly
set `setup_failure_policy: warn`.

### `setupTimeout` (F6)

`setupTimeout` (Action input, default `10m`) bounds the setup-script
wall-clock duration. A hanging install stalls the run otherwise. The
setup runs as a session leader (`start_new_session=True`), so a TERM →
grace → KILL on the deadline reaches the **whole** process tree — the
script's own children and grandchildren are reaped, not just the leader.

### Configuration guards

The Action validates combinations at setup time and fails closed as
`RunOutcome.configuration_error` *before* the agent runs. The most
common one bites operators who set `timeout: 10m` (the default)
together with their own `setupScript`:

- **`setupTimeout` must be strictly less than `timeout`.** Equal
  budgets let the setup script eat the whole run deadline; the agent
  is then given ≈1 ms and a setup timeout surfaces as
  `RunOutcome.timed_out` instead of the `inconclusive` /
  `configuration_error` the setup policy was supposed to produce. The
  guard fires before the setup subprocess spawns and reports a runtime
  reason along the lines of:

  > setup_timeout (X s) must be less than the run timeout (Y s) so a
  > failed setup script is not masked as an agent timeout

  Workaround: lower `setupTimeout` (e.g. `5m` with a `10m` run timeout)
  or raise `timeout`. Operators who explicitly opt in via `setupFailurePolicy`
  still need a non-zero agent budget — this guard is independent of the
  policy.

### Redaction (convention 7)

Setup-script stderr that surfaces to the agent prompt **or** the `result`
payload is passed through `analyzers.redact.redact_secrets` first.
Secrets (`ghp_…`, `sk-…`, `AKIA…`, etc.) become `[REDACTED]` in both
output channels.

### Skipping on untrusted tiers (convention 8)

`setup_script` is never executed on untrusted tiers (fork PRs,
`pull_request_target`, etc.). The trust check at `main.py:368` precedes
every subprocess spawn and is **not** moved by S1. When skipped, the
reason is recorded on `tool_state.setup_script_skip_reason` and threaded
into the agent prompt as a `SETUP SCRIPT SKIPPED` section so the agent
knows the setup did not run.

## Operator checklist

1. Unknown key on a security/runtime model → fix the typo; the Action will
   not run with a softened config.
2. Broken YAML → fix the file; until then defaults apply (restricted push/shell).
3. Bad `timeout` input → use a duration (`10m`, `1h30m`) or `--notimeout`.
4. Bad `setup_timeout` input → use a duration (`10m`, `1h30m`); the default
   (`10m`) is set even when `timeout` is unset or `--notimeout`.
5. Unknown `setup_failure_policy` value → fix the typo; the run fails closed
   as `configuration_error` before any subprocess spawns (closed vocabulary:
   `inconclusive` | `fail` | `warn`).
6. Setup script exits non-zero under default policy → the run is
   `inconclusive` (not `passed`). Set `setup_failure_policy: warn` to get
   today's continue-on-failure behaviour back, or fix the script.
7. Setup script hangs → it is killed at the `setupTimeout` deadline (default
   10 m) along with any children. Bump `setupTimeout` for slow installs.
8. Setup timeout ≥ run timeout → `configuration_error` — lower
   `setupTimeout` or raise `timeout` (see the Configuration guards note
   above). Equal deadlines are the most common landmine because the
   default `setupTimeout` (`10m`) and a `timeout: 10m` Action input
   collide exactly.
9. Prep install failed → treat the check conclusion as inconclusive/neutral
   and re-run after fixing the install error.
