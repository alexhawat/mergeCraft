# Observability and evaluation — test plan

Wave plan: `.ignorelocal/waves/04-observability-eval-wave-plan.md`
Worktree: session worktree on branch `alexhawat-observability-eval-waves` (based on `pre-0.0.1`).

This doc is appended to per sub-wave. So far: **PR OB1 (sub-wave OB1.1,
reconciled post-OB1.2)**, **PR OB2 (sub-wave OB2.1, reconciled post-OB2.2)**
and **PR OB3 (sub-wave OB3.1)**, **PR EV1 (sub-wave EV1.1, reconciled
post-EV1.2)**. The OB4 / EV2–EV3 sections will be appended by their own
`test-creator` sub-waves as those PRs start.

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
xfail-reconciliation: **post-OB2.2** — complete (2026-08-17): OB2.2 (`178f97c`)
made all 13 RED tests XPASS; the non-strict `green after OB2.2` markers were
removed and the suite is 13/13 clean real passes, 0 xfail/xpass.

Locked decisions covered: **D6** (four capture levels — `off` / `metadata` /
`redacted` / `full` — default `redacted`), **D7** (an untrusted trust tier is
capped at `metadata` and this cannot be configured away — not by YAML config,
not by env var; the security assertion), **D8** (content hash emitted at every
level above `off`). Also pins: bodies capped with a `.truncated` marker,
original size reported before truncation, invalid level falls back to the
default (fail safe, never open to `full`).

### xfail schedule (historical)

All 13 tests in `tests/tracing/test_content_policy.py` carried
`@pytest.mark.xfail(reason="green after OB2.2: …", strict=False)` —
`strict=False` was explicit because the repo pins `xfail_strict = true`. The
`mergecraft.tracing.content` import was lazy (fixture) so collection stayed
clean. OB2.2 (`178f97c`) turned all 13 into XPASS; the markers were removed in
the post-OB2.2 reconciliation, so the suite ends with 13 clean real passes.

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

At RED-suite time (OB2.1): 13 collected; **0 pass**; **13 RED** (non-strict xfail —
failures at runtime, zero collection errors). Post-OB2.2 reconciliation:
**13 passed, 0 xfail/xpass**. `make lint` + `make typecheck` clean. Live gates:
none in OB2.1 — `skipped: no live gate` (the fork-PR runtime proof is the OB2
Final gate, with blocking `security-review`).

## PR OB3 — model parameters, LLM input/output and reasoning capture (test plan OB3.1)

Authoring wave: **OB3.1** (tests-first, RED). Implementation: **OB3.2**.
xfail-reconciliation: **post-OB3.2** — complete (2026-08-17): OB3.2 (`d4c1c54`)
made the 15 RED tests XPASS; the non-strict `green after OB3.2` markers were
removed and the suite is 16/16 clean real passes, 0 xfail/xpass.

**Post-OB3.2 test amendment (escalation receiver):** `test_request_params_reach_the_span`'s
fixture model id was changed from `anthropic/claude-opus-4.8` to `claude-opus-test` —
the sink path routes string attrs through the pre-existing entropy redactor
(`redact_secrets`, ≥20 chars at entropy ≥ 4.0), which rewrote the realistic slug
to `[REDACTED].8`. Rationale (orchestrator ruling): the redaction layer is a
security boundary and is NOT changing; the test bends, keeping the builder-level
assertions in the sibling tests as-is.

Locked decisions covered: **D9** (reasoning inherits the prompt/content gate —
never a looser one), **D11** (record BOTH requested and executed model; a
fallback is visible as the mismatch). Findings covered: **O4** (no request
parameters), **O5** (no prompt/completion bodies), **O6** (no reasoning
capture). Global convention 6 (OTel GenAI names; mergeCraft-specific additions
under `mergecraft.*`) and convention 4 (all bodies route through OB2's
`capture_text` — no second policy mechanism) are pinned throughout.

**Harness coverage is genuinely partial** (plan §OB3.1 note): mergeCraft sees
model payloads only on the OpenCode HTTP path and in
`src/mergecraft/agents/_stream_consumer.py` — never for the CLI harnesses. All
15 contract tests pin the **pure builders** in `tracing/genai.py` and the
shared `_tool_attrs.py` helpers; no test asserts per-harness payload coverage
(OB3.2 File 2 wiring), so nothing implies uniform coverage.

### xfail schedule (historical)

15 of 16 tests carried `@pytest.mark.xfail(reason="green after OB3.2: …",
strict=False)` — `strict=False` was explicit because the repo pins
`xfail_strict = true`. `tests/tracing/test_tool_detail.py::test_existing_tool_attrs_unchanged`
was never xfailed (regression pin on the pre-OB3 `_tool_attrs` surface). The
`mergecraft.tracing.genai` import was lazy (shared fixture in
`tests/tracing/conftest.py`) so collection stayed clean. OB3.2 (`d4c1c54`)
turned the 15 into XPASS; the markers were removed in the post-OB3.2
reconciliation, so the suite ends with 16 clean real passes.

### Attribute-name contract pinned by these tests (convention 6)

| Attribute | Source |
| --- | --- |
| `gen_ai.request.model` / `gen_ai.response.model` | `request_attrs` / `response_attrs` (D11 — both, always) |
| `gen_ai.request.{temperature,top_p,top_k,max_tokens,stop_sequences,seed}` | `request_attrs` from `ModelParams`; unset knobs omitted, never zeroed |
| `mergecraft.reasoning_effort` / `mergecraft.thinking_budget` | `request_attrs` — no stable OTel name exists, so these live under `mergecraft.*` |
| `gen_ai.input.messages` / `gen_ai.output.messages` (+ `.chars` / `.bytes` / `.sha256` / `.truncated`) | `input_messages_attrs` / `output_messages_attrs` via `capture_text` |
| `gen_ai.input.messages.count` / `gen_ai.output.messages.count` | message count beside the body/hash |
| `mergecraft.thinking` (+ `.chars` / `.bytes` / `.sha256` / `.truncated`) | `thinking_attrs` via `capture_text` (D9 — same gate as prompts) |
| `mergecraft.thinking.provider_redacted` | `thinking_attrs(provider_redacted=True)` — distinguishes provider-redacted from empty |
| `mergecraft.usage.reasoning_tokens` | `thinking_attrs(reasoning_tokens=…)` — no stable OTel name |
| `gen_ai.tool.call.id` | new `call_id` kwarg on both `enrich_tool_request` and `enrich_tool_response` |
| `tool.duration_ms` | new `duration_ms` kwarg on `enrich_tool_response` |
| `tool.origin` (`"mcp"` / `"native"`) | new `tool_origin` kwarg on `enrich_tool_request` |

### Contract → test mapping

| Contract | Test | File |
| --- | --- | --- |
| O4 — every set knob reaches the span under its OTel GenAI name | `test_request_params_reach_the_span` | `tests/tracing/test_model_params.py` |
| O4 — unset knob omitted, not zeroed | `test_unset_knob_is_omitted_not_zeroed` | `tests/tracing/test_model_params.py` |
| D11 — executed model recorded beside requested | `test_response_model_recorded_beside_request_model` | `tests/tracing/test_model_params.py` |
| D11 — fallback visible as request/response mismatch | `test_fallback_is_visible_as_a_model_mismatch` | `tests/tracing/test_model_params.py` |
| O5 — input messages under policy, bodies through the matcher | `test_input_messages_captured_under_policy` | `tests/tracing/test_llm_payloads.py` |
| O5 — output messages under policy | `test_output_messages_captured_under_policy` | `tests/tracing/test_llm_payloads.py` |
| O5 — message count beside body/hash, both directions | `test_message_count_recorded` | `tests/tracing/test_llm_payloads.py` |
| O5 + D6 — bodies absent at `metadata`; hash/counts remain | `test_bodies_absent_at_metadata_level` | `tests/tracing/test_llm_payloads.py` |
| O6/D9 — reasoning text under the SAME policy as prompts | `test_reasoning_text_captured_under_policy` | `tests/tracing/test_thinking.py` |
| O6 — reasoning token count recorded | `test_reasoning_tokens_recorded` | `tests/tracing/test_thinking.py` |
| O6 — provider-redacted ≠ empty | `test_provider_redacted_thinking_is_distinguishable_from_empty` | `tests/tracing/test_thinking.py` |
| D9 — no configuration lets reasoning past the gate (untrusted + `full` → no body) | `test_reasoning_never_bypasses_the_gate` | `tests/tracing/test_thinking.py` |
| Tool detail — `gen_ai.tool.call.id` on both sides | `test_tool_call_id_correlates_request_and_response` | `tests/tracing/test_tool_detail.py` |
| Tool detail — duration recorded | `test_tool_call_records_duration` | `tests/tracing/test_tool_detail.py` |
| Tool detail — MCP vs native distinguished | `test_mcp_vs_native_tool_is_distinguished` | `tests/tracing/test_tool_detail.py` |
| Tool detail — existing attrs unchanged (**green pin**) | `test_existing_tool_attrs_unchanged` | `tests/tracing/test_tool_detail.py` |

### Target API OB3.2 must satisfy (as pinned by these tests)

`src/mergecraft/tracing/genai.py` (new):

| Symbol | Contract |
| --- | --- |
| `ModelParams` | Value type: `temperature`, `top_p`, `top_k`, `max_tokens`, `stop`, `seed`, `reasoning_effort`, `thinking_budget` — all optional, default unset |
| `request_attrs(model=, params=)` | `gen_ai.request.model` + set knobs only, under the names in the table above |
| `response_attrs(model=)` | `gen_ai.response.model` |
| `usage_attrs` | Token usage attrs (existing `gen_ai.usage.*` names) |
| `input_messages_attrs(messages, policy=)` / `output_messages_attrs(messages, policy=)` | Serialized bodies via `capture_text` at the `gen_ai.{input,output}.messages` prefix + `.count` |
| `thinking_attrs(text, policy=, reasoning_tokens=None, provider_redacted=False)` | Reasoning via `capture_text` at the `mergecraft.thinking` prefix + the two `mergecraft.*` extras above |

`src/mergecraft/tracing/_tool_attrs.py`:

| Symbol | Contract |
| --- | --- |
| `enrich_tool_request(span, *, arguments, call_id=None, tool_origin=None)` | New optional kwargs → `gen_ai.tool.call.id` / `tool.origin`; existing attrs unchanged |
| `enrich_tool_response(span, *, output, error=None, call_id=None, duration_ms=None)` | New optional kwargs → `gen_ai.tool.call.id` / `tool.duration_ms`; existing attrs unchanged |

### Acceptance (plan §OB3.1)

At RED-suite time (OB3.1): 16 collected; **1 passes** (`test_existing_tool_attrs_unchanged`);
**15 RED** (non-strict xfail — failures at runtime, zero collection errors).
Post-OB3.2 reconciliation: **16 passed, 0 xfail/xpass**. `make lint` +
`make typecheck` clean. Live gates: none in OB3.1 — `skipped: no live gate`
(the reasoning-model Logfire proof is the OB3 Final gate).

## PR EV1 — repair the corpus run path and publish reproducible numbers (test plan EV1.1)

Authoring wave: **EV1.1** (tests-first, RED). Implementation: **EV1.2**.
xfail-reconciliation: **post-EV1.2** — complete (2026-08-17): EV1.2 (`b1b5452`)
made all 6 RED tests XPASS; the non-strict `green after EV1.2` markers were
removed and the suite is 6/6 clean real passes, 0 xfail/xpass.
Closes **#219** (raw-findings run dir splits on slashes in model slugs),
**#220** (live corpus review runs in an empty scratch cwd and loses repo
context), **#140** (publish reproducible benchmark numbers with full version
pins). Finding covered: **O10**.

### xfail schedule (historical)

All 6 contract tests carried `@pytest.mark.xfail(reason="green after EV1.2: …",
strict=False)` — `strict=False` was explicit because the repo pins
`xfail_strict = true`. EV1.2 (`b1b5452`) turned all 6 into XPASS; the markers
were removed in the post-EV1.2 reconciliation, so the suite ends with 6 clean
real passes. At RED time each test failed for exactly one intended reason
(verified with `--runxfail`):

- `test_run_dir.py` — assertion failures: the run dir is nested
  (`raw-findings/openrouter-openrouter/openai/gpt-5-…`) instead of one flat
  component (#219).
- `test_live_context.py` — `ImportError: materialize_case_repo` (lazy import,
  collection stays clean) and an assertion that the case repo file is absent
  from the review cwd at review time (#220).
- `test_reproducibility.py` — `AttributeError`:
  `BenchmarkResultSet.reproducibility_digest` and `VersionPins.mergecraft_version`
  do not exist yet (#140).

### Detection-corpus layout contract pinned by these tests

A detection case (already: `<case_dir>/<patch>` + `<case_dir>/baseline.json`)
may additionally carry **`<case_dir>/repo/`** — the case's pre-patch file tree.
This is the EV1.2 corpus-format addition that closes #220 without handing the
reviewer the operator's real checkout.

### Contract → test mapping

| Contract | Test(s) | File |
| --- | --- | --- |
| #219 — slash-bearing slug → exactly one flat run dir under `raw-findings/`; sanitized, not truncated (every slug segment survives) | `test_model_slug_with_slash_does_not_split_the_run_dir` | `tests/evals/test_run_dir.py` |
| #219 — run-dir naming shape is uniform across providers (incl. routed slugs) and run dirs stay distinct | `test_run_dir_is_stable_across_providers` | `tests/evals/test_run_dir.py` |
| #220 — materialized review cwd contains the case's repo files; never an empty scratch dir | `test_live_review_runs_with_real_repo_context` | `tests/evals/test_live_context.py` |
| #220 — ordering: repo is materialized *before* the review on the production default path (`review_fn=None`) | `test_case_repo_is_materialized_before_review` | `tests/evals/test_live_context.py` |
| #140 — same commit + same corpus ⇒ same result set, via a digest that excludes `pins.recorded_at` | `test_same_commit_yields_the_same_result_set` | `tests/evals/test_reproducibility.py` |
| #140 — every version pin recorded, incl. the mergeCraft distribution version | `test_result_set_records_every_version_pin` | `tests/evals/test_reproducibility.py` |

### Target API EV1.2 must satisfy (as pinned by these tests)

`src/mergecraft/evals/live_run.py`:

| Symbol | Contract |
| --- | --- |
| run-id construction in `run_live_detection` | Slug sanitized so the run dir is always one path component under `raw-findings/`; all slug segments preserved (no truncation collisions) |
| `materialize_case_repo(case, dest) -> Path` (new) | Copies `<case_dir>/repo/` into `dest`, returns `dest` |
| production `ReviewFn` (`_default_review_fn` path) | Materializes the case repo *before* calling `run_offline_diff_review`; the review `cwd` is the materialized tree |

`src/mergecraft/evals/benchmark.py`:

| Symbol | Contract |
| --- | --- |
| `BenchmarkResultSet.reproducibility_digest` (new) | Non-empty content hash over the result set excluding volatile wall-clock fields (`pins.recorded_at`); equal for two replays at one commit + corpus |
| `VersionPins.mergecraft_version` (new) | The installed mergeCraft distribution version (`mergecraft.__version__`), alongside the existing commit pin |

### Acceptance (plan §EV1.1, post-reconciliation)

6 collected; **6 passed**; 0 xfail/xpass (RED acceptance at authoring time was
6 collected / 0 pass / 6 RED — met at `1c0881c`). `make lint` +
`make typecheck` clean. Live gates: none in EV1.1 — all six tests are keyless
(stub `review_fn` / stubbed `run_offline_diff_review` boundary), so
`skipped: no live gate` applies cleanly; the live-provider proof is the EV1
Final gate.
