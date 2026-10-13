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
and never restored it. The patch becomes a non-autouse `monkeypatch` fixture or
is deleted with the tests that needed it.

| Behaviour | Layer | Test |
| --- | --- | --- |
| After any `tests/scm/` test has run, httpx carries no patch marker; signature verification needs no process-wide patch | unit | `tests/scm/test_httpx_patch_is_scoped.py::test_httpx_models_carries_no_process_wide_patch_marker` |
| When the compat module survives, the applying fixture is non-autouse and restores via `monkeypatch` | integration | `tests/scm/test_httpx_patch_is_scoped.py::test_the_patch_is_monkeypatch_scoped_or_deleted` |

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
  no ingress path; a compat module that survives versus one that is deleted;
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
