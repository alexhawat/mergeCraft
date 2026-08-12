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
| Syntactically broken `.mergecraft/config.yaml` | Warn, fall back to `default_settings()` |
| Nested informational blocks (`staticChecks`, `ciEvidence`, mode defs, sink entries, …) | Unknown keys warn for one release (`extra="ignore"` + warning shim), then flip to `forbid` |
| Trusted-tier `setupScript` non-zero exit | Warn-only; the run continues (untrusted tiers never execute it — trust ordering) |
| Learnings seed / bundled-skills install failure | Warn and continue without that feature |

Review-relevant **prep / dependency-install** failure is a third shape: the
run maps to `RunOutcome.inconclusive` with the install reason recorded
(not `passed`, not a silent continue). That is fail-closed for the
*outcome*, not a hard abort before the agent starts.

## Operator checklist

1. Unknown key on a security/runtime model → fix the typo; the Action will
   not run with a softened config.
2. Broken YAML → fix the file; until then defaults apply (restricted push/shell).
3. Bad `timeout` input → use a duration (`10m`, `1h30m`) or `--notimeout`.
4. Prep install failed → treat the check conclusion as inconclusive/neutral
   and re-run after fixing the install error.
