# Observability and evaluation — test plan

Wave plan: `.ignorelocal/waves/04-observability-eval-wave-plan.md`
Worktree: session worktree on branch `alexhawat-observability-eval-waves` (based on `pre-0.0.1`).

This doc is appended to per sub-wave. So far: **PR OB1 (sub-wave OB1.1,
reconciled post-OB1.2)** and **PR OB2 (sub-wave OB2.1)**. The OB3–OB4 /
EV1–EV3 sections will be appended by their own `test-creator` sub-waves as
those PRs start.

## PR OB1 — review-wide correlation on every span (test plan OB1.1)

Authoring wave: **OB1.1** (tests-first, RED). Implementation: **OB1.2**.
xfail-reconciliation: **post-OB1.2** — complete (2026-08-17): OB1.2 (`3891020`)
made all 14 RED tests XPASS; the non-strict `green after OB1.2` markers were
removed and the suite is 15/15 clean real passes, 0 xfail/xpass.

Locked decisions covered: **D2** (three identifiers), **D3** (review_id not
derived from head SHA; `correlation_key` deliberately collides across attempts),
**D4** (review attrs merge inside `Span.close()`, read at close time; precedence
baseline → review context → lazy `attrs_source` → explicit `set_attribute`),
**D5** (`Tracer.baseline_attrs` with `repr=False`). Findings covered: **O1**
(no review-wide identity), **O2** (identity must cross the subprocess boundary),
**O3** (spans self-describing: version + VCS/CI fields).

### xfail schedule (historical)

All 14 contract tests carried `@pytest.mark.xfail(reason="green after OB1.2: …",
strict=False)` — `strict=False` was explicit because the repo pins
`xfail_strict = true`. The D5 repr pin was never xfailed. OB1.2 (`3891020`)
turned all 14 into XPASS; the markers were removed in the post-OB1.2
reconciliation, so the suite ends with 15 clean real passes.

### Env-var contract pinned by these tests (not fixed in prose by the plan)

| Env var | Meaning |
| --- | --- |
| `MERGECRAFT_REVIEW_ID` | The review-wide id, inherited by spawned agent subprocesses (O2). |
| `MERGECRAFT_REVIEW_CORRELATION_KEY` | The deterministic attempt-colliding key (D2/D3), exported alongside. |

### Span-attribute contract pinned by these tests

| Attribute | Source |
| --- | --- |
| `review.id` | Bound `ReviewContext.review_id`; on every span kind (O1/D2). |
| `review.correlation_key` | Bound `ReviewContext.correlation_key`; omitted when empty (`attrs()` drops empty values). |
| `mergecraft.run_id` / `mergecraft.version` / `mergecraft.trust_tier` | `baseline_run_attrs()` (O3). |
| `vcs.repository.name` / `vcs.change.id` / `vcs.revision` | `baseline_run_attrs()` from `resolve_correlation_from_env()` (O3). |
| `ci.workflow_run_id` / `ci.job_id` | `baseline_run_attrs()` from `resolve_correlation_from_env()` (O3). |

### Contract → test mapping

| Contract | Test(s) | File |
| --- | --- | --- |
| O1 — review.id on every span kind | `test_review_id_lands_on_every_span` | `tests/tracing/test_review_context.py` |
| O1 — stability within a review (across runs/tracers) | `test_review_id_is_stable_within_a_review` | `tests/tracing/test_review_context.py` |
| D2 — three runs, one review: 1 review.id + 3 trace_ids | `test_trace_id_is_per_run_not_per_review` | `tests/tracing/test_review_context.py` |
| D3 — deterministic `sha256(repo\|pr\|head_sha)` | `test_correlation_key_is_deterministic` | `tests/tracing/test_review_context.py` |
| D3 — key collides across attempts, review_id never does | `test_correlation_key_differs_from_review_id_across_attempts` | `tests/tracing/test_review_context.py` |
| D3 — no repo context → empty key, attr omitted (no misleading constant) | `test_correlation_key_is_empty_without_repo_context` | `tests/tracing/test_review_context.py` |
| D4 — close-time merge: context bound after tracer/span creation still lands | `test_context_bound_after_tracer_creation_still_reaches_spans` | `tests/tracing/test_review_context.py` |
| D4 — precedence: explicit `set_attribute` beats review context | `test_precedence_explicit_attr_beats_review_context` | `tests/tracing/test_review_context.py` |
| O3 — baseline attrs carry version + VCS/CI fields; tracer baseline reaches spans | `test_baseline_attrs_carry_version_and_vcs_fields` | `tests/tracing/test_review_context.py` |
| D5 — repr unchanged (`baseline_attrs` is `repr=False`) — **green pin** | `test_tracer_repr_is_unchanged` | `tests/tracing/test_review_context.py` |
| O2 — `spawn_agent_cli` hands review env to `subprocess.Popen` (real call site, not a patched helper) | `test_spawn_agent_cli_exports_review_env` | `tests/tracing/test_review_env_propagation.py` |
| O2 — child reuses the inherited review id; uuid4 fallback otherwise | `test_child_process_reuses_the_inherited_review_id` | `tests/tracing/test_review_env_propagation.py` |
| O2 — fail-closed setpriv error surfaces first (injection after `agent_subprocess_env`) | `test_privilege_error_still_surfaces_first` | `tests/tracing/test_review_env_propagation.py` |
| O2 — explicit caller value wins (`setdefault`, not overwrite) | `test_explicit_caller_value_wins` | `tests/tracing/test_review_env_propagation.py` |
| O1/O3 — CLI (`offline_review.py`) and Action (`main.py`) both bind a `ReviewContext` | `test_both_entry_points_emit_review_id_and_baseline` | `tests/tracing/test_cli_action_parity.py` |

### Target API OB1.2 must satisfy (as pinned by these tests)

`src/mergecraft/tracing/review_context.py` (new):

| Symbol | Contract |
| --- | --- |
| `ReviewContext` | Frozen dataclass: `review_id`, `correlation_key`, `attempt`, `source`, `repo`, `pr_number`, `base_ref`, `base_sha`, `head_ref`, `head_sha`, `mode`, `trigger`, `trust_tier` |
| `ReviewContext.attrs()` | Span-attr dict; drops empty values rather than emitting nulls |
| `bind_review_context(ctx)` | Context manager binding the ctx (ContextVar) for the dynamic scope |
| `resolve_review_id()` | `MERGECRAFT_REVIEW_ID` inherited verbatim → else fresh `uuid4` per call |
| `correlation_key_for(repo=, pr_number=, head_sha=)` | `sha256(f"{repo}\|{pr_number}\|{head_sha}")` hexdigest; `""` without full repo context |
| `review_env_for_subprocess()` | Env mapping for spawned children (consumed by `spawn_agent_cli`) |

`src/mergecraft/tracing/tracer.py`:

| Symbol | Contract |
| --- | --- |
| `Tracer.baseline_attrs` | New field, `repr=False` (D5); merged first in `Span.close()` (D4) |
| `baseline_run_attrs()` | `mergecraft.{run_id,version,trust_tier}`, `vcs.{repository.name,change.id,revision}`, `ci.{workflow_run_id,job_id}` from `resolve_correlation_from_env()` + `mergecraft.__version__` |

`src/mergecraft/agents/shared.py::spawn_agent_cli`: exports the review env into
the child **after** `agent_subprocess_env`, via `setdefault` (O2).

`src/mergecraft/offline_review.py` + `src/mergecraft/main.py`: bind a
`ReviewContext` at each entry point (parity asserted, not assumed).

### Acceptance (plan §OB1.1)

At RED-suite time (OB1.1): 15 collected; **1 passes** (`test_tracer_repr_is_unchanged`);
**14 RED** (non-strict xfail — failures at runtime, zero collection errors).
Post-OB1.2 reconciliation: **15 passed, 0 xfail/xpass**. `make lint` +
`make typecheck` clean. Live gates: none in OB1.1 — `skipped: no live gate`.

## PR OB2 — content-capture policy for model payloads (test plan OB2.1)

Authoring wave: **OB2.1** (tests-first, RED). Implementation: **OB2.2**.
xfail-reconciliation: **post-OB2.2** (orchestrator re-dispatches test-creator to
remove the satisfied markers).

Locked decisions covered: **D6** (four capture levels — `off` / `metadata` /
`redacted` / `full` — default `redacted`), **D7** (an untrusted trust tier is
capped at `metadata` and this cannot be configured away — not by YAML config,
not by env var; the security assertion), **D8** (content hash emitted at every
level above `off`). Also pins: bodies capped with a `.truncated` marker,
original size reported before truncation, invalid level falls back to the
default (fail safe, never open to `full`).

### xfail schedule

All 13 tests in `tests/tracing/test_content_policy.py` carry
`@pytest.mark.xfail(reason="green after OB2.2: …", strict=False)` —
`strict=False` is explicit because the repo pins `xfail_strict = true`. The
`mergecraft.tracing.content` import is lazy (fixture) so collection stays clean.
After OB2.2 lands, the markers are removed in reconciliation so the suite ends
with 13 clean real passes.

### Env-var contract pinned by these tests (not fixed in prose by the plan)

| Env var | Meaning |
| --- | --- |
| `MERGECRAFT_TRACING_CONTENT` | Capture-level override; beats YAML `tracing.content` (normal precedence) but never beats the D7 untrusted cap. Follows the existing `MERGECRAFT_TRACING*` family in `src/mergecraft/cli/tracing_precedence.py`. |

### Span-attribute contract pinned by these tests

`capture_text(payload, prefix, policy, max_bytes)` emits, for the given
`prefix` (e.g. `gen_ai.input`):

| Attribute | Levels | Content |
| --- | --- | --- |
| `<prefix>` | `redacted`, `full` | Body — through `analyzers.redact.redact_secrets` at `redacted`, verbatim at `full`; capped at `max_bytes` (default `cap.TRACE_ATTRS_JSON_MAX_BYTES`). |
| `<prefix>.chars` | above `off` | Original payload length in chars (before truncation). |
| `<prefix>.bytes` | above `off` | Original payload length in bytes (before truncation). |
| `<prefix>.sha256` | above `off` (D8) | sha256 hexdigest of the **original** payload — identical across levels so it detects drift even between two runs that shipped no body. |
| `<prefix>.truncated` | body levels | `True` when the emitted body was cut by `max_bytes`. |

### Contract → test mapping

All tests live in `tests/tracing/test_content_policy.py`.

| Contract | Test(s) |
| --- | --- |
| D6 — `off` emits nothing (no body, no metadata, no hash) | `test_off_emits_nothing` |
| D6/D8 — `metadata` emits counts + hash only, never the body | `test_metadata_emits_counts_and_hash_only` |
| D6 — `redacted` body is exactly `redact_secrets(payload)` (no second redactor) | `test_redacted_emits_body_through_the_secret_matcher` |
| D6 — `full` body verbatim, capped only (secret matcher not applied) | `test_full_emits_body_capped_only` |
| D6 — default is `redacted` (resolver `None` + `TracingSettings.content` default) | `test_default_is_redacted` |
| D7 — untrusted tier capped at `metadata`; cap never raises `off` | `test_untrusted_tier_is_capped_at_metadata` |
| D7 — `content: full` in YAML still yields `metadata` untrusted | `test_untrusted_cap_cannot_be_overridden_by_config` |
| D7 — `MERGECRAFT_TRACING_CONTENT=full` still yields `metadata` untrusted | `test_untrusted_cap_cannot_be_overridden_by_env` |
| Precedence — env beats config at a trusted tier | `test_env_beats_config_at_trusted_tier` |
| D8 — hash at every level above `off` (of the original payload) | `test_hash_is_emitted_at_every_level_above_off` |
| Capping — body cut at `max_bytes`, `.truncated` marker; default cap is `TRACE_ATTRS_JSON_MAX_BYTES` | `test_body_is_capped_and_marked_truncated` |
| Capping — `.chars` / `.bytes` / `.sha256` describe the original payload | `test_original_size_is_reported_before_truncation` |
| Fail safe — invalid level (config or env) falls back to `redacted`, never `full` | `test_invalid_level_falls_back_to_default_not_full` |

### Target API OB2.2 must satisfy (as pinned by these tests)

`src/mergecraft/tracing/content.py` (new):

| Symbol | Contract |
| --- | --- |
| `ContentCapture` | StrEnum: `off` / `metadata` / `redacted` / `full` |
| `ContentCapture.emits_body` | `True` at `redacted` + `full` only |
| `ContentCapture.emits_metadata` | `True` at `metadata` + `redacted` + `full` only |
| `resolve_content_capture(configured, trust_tier)` | Precedence: `MERGECRAFT_TRACING_CONTENT` env → `configured` → `redacted` default; invalid values fall back to `redacted` (never `full`); `untrusted` tier caps the result at `metadata` (cap never raises `off`) |
| `capture_text(payload, prefix, policy, max_bytes=TRACE_ATTRS_JSON_MAX_BYTES)` | Emits the attribute table above; `{}` at `off`; reuses `analyzers.redact.redact_secrets` — no second redaction or capping mechanism |

`src/mergecraft/config/settings.py`:

| Symbol | Contract |
| --- | --- |
| `TracingSettings.content` | New field, default `"redacted"`; accepted by the (extra-forbidding) YAML model |

### Acceptance (plan §OB2.1)

13 collected; **0 pass**; **13 RED** (non-strict xfail — failures at runtime,
zero collection errors). `make lint` + `make typecheck` clean. Live gates:
none in OB2.1 — `skipped: no live gate` (the fork-PR runtime proof is the OB2
Final gate, with blocking `security-review`).
