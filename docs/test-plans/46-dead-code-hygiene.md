# Test plan — controls built and never connected: an inert webhook, unwired seams, test seams in runtime source

**Owner:** `test-creator` · **Branch:** `wave/dead-code-hygiene` · **Base:** `origin/main` @ `0136dba2`
**Trace run:** service `mergecraft-dev` · wave.plan=dead-code-hygiene · run.id=`6792a2d5-b6f0-44d1-9cf2-9ccb2670de84`

This document maps each behaviour the RED suite pins to the tests that hold it.
Every deletion ships a test that pins the surface that survives: a removed
route changes no behaviour the run observed, but the advertised surface does,
so the pin is on the surface — route absent, key refused, module gone,
residency still enforced.

**Status: RED as committed.** Collection is clean, `make lint` and `make
typecheck` exit 0, and 50 authored tests fail because the code they name has
not been removed or changed yet. No test is skipped or xfailed to mask a
contract; a removed surface is a plain failure until the deletion lands. The
three passing tests and the single `xfail` in this set are pre-existing
neighbours in `tests/utils/test_privilege_identity.py`, not new pins.

Verification commands:

```bash
UV_PROJECT_ENVIRONMENT="$PWD/.venv-dev" MERGECRAFT_PYTEST_JOBS=0 uv run pytest <paths> -q -rxX
UV_PROJECT_ENVIRONMENT="$PWD/.venv-dev" make lint && make typecheck
```

## Names this suite pins

A few seams were open when the suite was written. The suite fixes them so the
removal waves have one target.

| Surface | Name | Shape |
| --- | --- | --- |
| Redaction canary hook | `tests/analyzers/support.assert_no_canary(text, canary)` | moves out of `mergecraft.analyzers.redact`; raises `AssertionError` on a leak, passes clean text |
| Recorded Jev transports | `tests/jev/support.RecordedTransport`, `tests/jev/support.FlakyRecordedTransport` | both classes live in the test-support module; the runtime module keeps `JevTransport` and `LiveTypeSafeTransport` |
| Provider-health surface | `mergecraft.agents.provider_health.__all__` | exactly `capability_catalog` and `enforce_residency` |
| Profile env exports | `mergecraft.cli.profiles.profile_env_overrides` | exactly `MERGECRAFT_TOKEN_BUDGET`, `MERGECRAFT_COST_BUDGET_USD`, `MERGECRAFT_TOOL_CALL_BUDGET` |
| Dispatch refusal | `mergecraft.agents.registry.load_registry` | raises `RegistryValidationError` for `dispatch: ensemble` / `shadow`, naming the mode; `single` and omitted resolve |

## Contract → test map

### The per-run MCP app mounts no webhook ingress route

The route authenticated a signed delivery and returned `200` without
processing anything. Removing it is the deliberate choice; the health probe
and the Bearer-guarded `/mcp` surface must be untouched.

| Behaviour | Layer | Test |
| --- | --- | --- |
| A `POST /webhooks/{provider}` is not a route (404/405) for github, gitlab and bitbucket; `/health` still answers `ok` | functional | `tests/mcp/test_server_webhook_route_absent.py::test_no_webhook_ingress_route_is_mounted`, `::test_no_provider_specific_webhook_path` |
| The Bearer-guarded `/mcp` surface still refuses an anonymous caller and serves the tool list to the bearer | functional | `tests/mcp/test_server_webhook_route_absent.py::test_no_provider_specific_webhook_path` |

### The support matrix advertises no webhook ingress for any SCM

| Behaviour | Layer | Test |
| --- | --- | --- |
| The generator's SCM table names no webhook role; GitHub review support stays "Supported" | unit | `tests/scm/test_support_matrix_webhook_row.py::test_generated_matrix_advertises_no_webhook_ingress` |
| The checked-in page carries no webhook row and still renders the other axes | integration | `tests/scm/test_support_matrix_webhook_row.py::test_committed_matrix_advertises_no_webhook_ingress` |

### No `tests/scm/` fixture patches httpx for the whole process

The autouse fixture installed a latin-1 header normaliser on `httpx._models`
and never restored it. Every test that needed it pushed non-ASCII header bytes
through `TestClient` on the webhook route, so the patch and its fixture are
deleted rather than scoped.

| Behaviour | Layer | Test |
| --- | --- | --- |
| After any `tests/scm/` test has run, httpx carries no patch marker; signature verification needs no process-wide patch | unit | `tests/scm/test_httpx_patch_is_scoped.py::test_httpx_models_carries_no_process_wide_patch_marker` |
| The compat module and its conftest wiring are gone, not merely scoped; non-ASCII headers still fail closed with plain dicts | integration | `tests/scm/test_httpx_patch_is_scoped.py::test_the_process_wide_patch_machinery_is_gone` |

### The provider-health module keeps only the called surfaces

Routing, circuit-breaker, budget and routing-eval helpers had no production
caller; `capability_catalog` (enterprise routing residency fallback) and
`enforce_residency` (enterprise residency policy) do. Residency enforcement
keeps working through both the direct helper and the enterprise gate.

| Behaviour | Layer | Test |
| --- | --- | --- |
| `__all__` is exactly the two called surfaces; the catalog still describes every capability dimension | unit | `tests/agents/test_provider_health_surface.py::test_module_exports_exactly_the_kept_surface` |
| Each unused callable, constant and dataclass is gone; the direct residency check still refuses a disallowed region | unit | `tests/agents/test_provider_health_surface.py::test_unwired_provider_helper_is_gone` |
| The enterprise routing gate still refuses an out-of-region model and passes an in-region one | integration | `tests/agents/test_provider_health_surface.py::test_enterprise_routed_model_residency_still_refuses_a_disallowed_region` |

### The four unwired context modules are gone

| Behaviour | Layer | Test |
| --- | --- | --- |
| On-demand expansion, repo map, git history and external files are not importable; the surviving context modules load and the `context` CLI verbs answer | integration | `tests/context/test_context_surface.py::test_unwired_context_module_is_gone` |

### `dispatch: ensemble | shadow` is refused

| Behaviour | Layer | Test |
| --- | --- | --- |
| An agent entry naming an unimplemented mode fails resolution with a config error naming the mode; an omitted key and an explicit `single` still resolve to `single` | integration | `tests/agents/test_registry_dispatch_refused.py::test_unimplemented_dispatch_mode_is_refused` |

### A profile exports only variables the run-bounds reader consumes

| Behaviour | Layer | Test |
| --- | --- | --- |
| No exported key is absent from `utils/run_bounds.py`; the latency and profile variables are gone; the budget bundle and the recorded latency field stay | unit | `tests/cli/test_profile_env_exports.py::test_profile_env_overrides_emits_no_unread_variable` |
| The exported set is exactly the three budget variables, and each one changes the bounds `resolve_run_bounds` returns | integration | `tests/cli/test_profile_env_exports.py::test_exported_budget_variable_actually_changes_resolved_bounds` |

### The policy surface says review does not enforce policy rules

| Behaviour | Layer | Test |
| --- | --- | --- |
| The `policy` group help states the limits and still advertises lint, test, explain and simulate | functional | `tests/cli/test_policy_help_honest.py::test_policy_group_help_says_review_does_not_enforce_rules` |
| The enforcement module docstring claims no approval-gate mapping; the evaluation engine still ships | unit | `tests/cli/test_policy_help_honest.py::test_enforcement_module_docstring_does_not_claim_an_approval_gate_mapping` |

### Test seams leave the runtime package

| Behaviour | Layer | Test |
| --- | --- | --- |
| `mergecraft.jev.client` exports neither recorded transport; the live protocol and transport stay | unit | `tests/jev/test_runtime_has_no_recorded_transport.py::test_runtime_client_has_no_recorded_transports` |
| `tests/jev/support.py` owns both recorded transports and still pins the replay fixtures | unit | `tests/jev/test_runtime_has_no_recorded_transport.py::test_tests_support_provides_both_recorded_transports` |
| `mergecraft.analyzers.redact` ships no canary hook; the shipped redactor still removes a canary | unit | `tests/analyzers/test_redact_surface.py::test_redact_module_no_longer_ships_assert_no_canary` |
| A tests helper owns the canary assertion and still fails on a leak | unit | `tests/analyzers/test_redact_surface.py::test_tests_helper_provides_assert_no_canary` |

### Zero-caller exported helpers go, with their modules' surfaces pinned

| Behaviour | Layer | Test |
| --- | --- | --- |
| `reviewer_p0_slug_from_config` is gone; the plain first-slug reader still works | unit | `tests/config/test_roster_unwired_surface.py::test_reviewer_p0_slug_from_config_is_gone` |
| `resolve_model_params_for_model` is gone; the shared endpoint resolver still resolves the singleton gateway | unit | `tests/agents/test_openai_compatible_gateways_surface.py::test_resolve_model_params_for_model_is_gone` |
| `secret_is_present` is gone; the read-only roster view still resolves a credential status | unit | `tests/cli/test_provider_status_surface.py::test_secret_is_present_is_gone` |
| `LENS_ROUTING_STEP4_NOTE` is gone from the module and the package re-export; the routing helpers still work | unit | `tests/review/test_lens_routing_surface.py::test_lens_routing_step4_note_is_gone` |

### The quarantined privilege pin becomes a ratchet

The only non-strict `xfail` in the named files is a test bug — the missing
passwd and bounding-set stubs the sibling supplies. The pin turns that
quarantine into a ratchet the privilege wave removes.

| Behaviour | Layer | Test |
| --- | --- | --- |
| No test in the file carries a non-strict `xfail`; the stubbed hardened-argv sibling stays a plain, passing test | unit | `tests/utils/test_privilege_identity.py::test_no_non_strict_xfail_remains_in_this_file` |

## Scenario classes

* **Happy path** — the surviving surfaces work without the deleted code: the
  health probe and Bearer-guarded `/mcp` route answer; signature verification
  accepts a signed payload; the capability catalog lists every dimension;
  residency passes an in-region model; `single` dispatch resolves; the
  endpoint resolver resolves the singleton gateway; the context verbs answer;
  the shipped redactor removes a canary; the plain roster reader returns the
  first reviewer slug.
* **Edge cases** — three SCM rows in the generated table; three providers with
  no ingress path; the compat module and its fixture deleted, with the
  process-wide marker absent;
  every unused name in the provider-health module, constants and dataclasses
  included; an omitted `dispatch` key beside an explicit one; three profiles
  and the full exported variable set; four removed context modules beside the
  seven surviving ones; the package re-export as well as the module export.
* **Error handling** — an unsigned or mismatched HMAC still raises
  `PermissionError`; an unimplemented dispatch mode fails resolution with a
  message that names the mode and says it is not implemented; a disallowed
  residency region still raises `PermissionError`; the canary helper raises
  `AssertionError` on a leak; the `policy` help must state that review does not
  enforce rules.

## Reconciliation log

The removal waves make each red section green; `test-creator` then re-reads
this document and reconciles the pins — removing the now-satisfied markers the
waves cannot touch themselves. No implementation wave edits a test, and no
assertion is weakened to reach green. This section records each pass.

### DC2b (2026-10-13) — prunes the pins of `07797935`

The prior wave (option A, `07797935`) removed the inert webhook route and the
ingress-only replay store; this pass prunes the `tests/scm/` pins that named the
removed code and finishes the process-wide-httpx-patch cleanup.

* **Deleted, pinned to removed code.** `tests/scm/test_ingress_idempotency.py`
  (imported `mergecraft.scm.ingress` — a hard collection error); the seven
  route/store tests in `tests/scm/test_cd_webhooks.py`
  (`test_webhook_replay_protection_rejects_stale_or_reused_delivery`,
  `test_webhook_event_processing_fails_closed_without_delivery_id`,
  `test_webhook_event_processing_is_idempotent_on_delivery_id`,
  `test_webhook_ingress_rejects_invalid_hmac_before_processing`,
  `test_webhook_ingress_verifies_then_processes_a_valid_payload`,
  `test_http_webhook_route_rejects_empty_secret_for_github_and_gitlab`,
  `test_http_webhook_route_accepts_signed_github_and_gitlab_deliveries`); and
  `test_webhook_headers.py::test_route_never_returns_500_on_an_unauthenticated_path`.
  The signature, rate-limit, conformance, permission and review-only tests stay.
* **The three surviving `tests/scm/test_webhook_headers.py` tests** call
  `verify_webhook_signature` directly with dicts, so the file drops its autouse
  latin-1 fixture and the `TestClient` / `_httpx_compat` imports with it.
* **The process-wide httpx patch.** Nothing needs it anymore, so
  `tests/scm/_httpx_compat.py` is deleted and `tests/scm/conftest.py` drops the
  `install_httpx_latin1_header_values` import and the autouse fixture. The pin
  `tests/scm/test_httpx_patch_is_scoped.py` now asserts the machinery is gone
  (module absent, conftest wiring absent) beside the surviving direct-header
  signature path; `test_httpx_models_carries_no_process_wide_patch_marker`
  asserts no `_mergecraft_latin1_patched` marker survives a run. No
  process-wide httpx mutation remains.
* **Stale wording.** `tests/scm/conftest.py` drops the "RED suite" title and the
  "not implemented yet" gate wording. `require_scm()` keeps a hard gate (the
  import itself) but now asserts the `ScmProvider` surface is importable; the
  vacuous `try/except _SCM_AVAILABLE` guard is collapsed.
* **Absence paired with survival.** No pin asserts an absence alone: every
  removed surface is paired with a surviving one (route absent ↔ `/health` and
  `/mcp` answer; compat module absent ↔ non-ASCII headers still fail closed;
  marker absent ↔ signature verification works).

**Evidence.** `MERGECRAFT_PYTEST_JOBS=0 uv run pytest tests/scm tests/mcp -q -rxX`
→ `1193 passed, 1 skipped` (no failures, no errors, no XPASS). `make lint`
exit 0 · `make typecheck` exit 0.

### DC3b (2026-10-13) — prunes the pins of the unwired-seam deletion

The product wave removed eleven provider routing/breaker/budget helpers with
their dataclasses and constants, four context-retrieval modules no review path
imported, two profile environment exports nothing read, and made
`dispatch: ensemble | shadow` a config error. This pass deletes the
pre-existing tests that named the removed code, retargets the one residency
test at the surviving function, and finishes the environment-variable
inventory.

* **Provider surface trimmed.** `tests/agents/test_ce_providers.py` keeps only
  the called surface: `capability_catalog` (every capability dimension), the
  residency allow-list check (an in-region pass and an out-of-region refusal),
  and the three non-regression guards beside them (retry classification, no
  OTLP exporter edit, no published cost-per-review). The thirteen tests that
  pinned `route_model`, `ProviderHealth`, `ProviderBreaker`,
  `verifier_judge_models`, `should_retry_provider`, `degrade_unavailable`,
  `resolve_required_model`, `manifest_provider_stamp`,
  `enforce_provider_budget`, `evaluate_routing_quality` and the nightly smoke
  are gone; `tests/agents/test_provider_health_surface.py` is the pin that the
  names are absent and the two called surfaces work.
* **Residency retargeted.** `tests/enterprise/test_runtime_enforcement.py`
  `test_residency_policy_blocks_routed_us_model` no longer imports the removed
  routing helper; it drives the surviving enterprise gate
  `enforce_routed_model_residency` on a catalog model — refused under an
  out-of-region allow-list, accepted under one that covers it. This is the one
  residency test on that function in the file; the in-region Vertex case beside
  it is unchanged.
* **Context modules pruned.**
  `tests/context/test_repo_map.py`, `test_dynamic_expansion.py` and
  `test_git_history.py` are deleted with the modules they imported.
  `tests/context/test_cc_instruction_sources.py` loses only the
  `external_files` string-load case (and its now-unused `pytest` import);
  `tests/context/test_cc_search_explain.py` drops `repo_map.py` and
  `git_history.py` from the retrieval half's file list.
  `tests/context/support.py` loses `write_dynamic_expansion_fixture_repo`,
  which the deleted expansion tests were its only callers. Every other context
  test stays, and `tests/context/test_context_surface.py` keeps pinning that
  the four modules are gone beside the seven that survive.
* **Environment inventory reconciled.** Deleting the webhook route, the
  nightly-smoke gate and the two profile exports left four `MERGECRAFT_*`
  names in `tests/docs/test_operator_env_vars.py` that `src/` no longer reads,
  so the document/never-document partition failed. The latency-budget name
  moves out of the documented set, and the profile, live-end-to-end and
  webhook-secret names out of the never-document set, so the two lists again
  classify exactly the names `src/` reads.
* **Left alone.** `tests/support/ce_batch.py` names no removed symbol (the
  provider-health module path still exists). `tests/cli/test_ce_profiles.py`
  and `tests/cli/test_profiles.py` assert no deleted environment key, so they
  keep the recorded `latency_budget_ms` field and pass unchanged.
* **Absence paired with survival.** No pruned test asserted an absence alone:
  the provider pin keeps the catalog and both residency outcomes beside the
  gone names, and the context pin keeps the surviving modules and the
  `context` verbs beside the removed ones.

**Evidence.** `MERGECRAFT_PYTEST_JOBS=0 uv run pytest tests/agents
tests/enterprise tests/context tests/policy tests/cli/test_policy_verbs.py
tests/cli/test_ce_profiles.py tests/cli/test_profiles.py -q -rxX` →
`1155 passed, 2 skipped`, with the one deliberate red left for the last
removal wave (`tests/agents/test_openai_compatible_gateways_surface.py::
test_resolve_model_params_for_model_is_gone`, which pins a helper that wave
still owns). `tests/docs` and the rest of the suite are green. `make lint`
exit 0 · `make typecheck` exit 0.

**Findings left to the operator.** `docs/cli.md`'s environment-variable table
still lists the latency-budget knob, which nothing exports or reads now;
product docs are outside the test writer's remit. The
`write_context_fixture_repo` helper in `tests/context/support.py` was used only
by the deleted repo-map test and is now orphaned; it was left in place because
the pruning hand-off named only the dynamic-expansion fixture.
