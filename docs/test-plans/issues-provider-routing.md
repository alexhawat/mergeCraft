# #71 / #37 — Provider routing & chain semantics — W1 RED test plan

Wave plan: `.ignorelocal/waves/issues-provider-routing-wave-plan.md`
Worktree: `mergecraft-prov-b-routing` @ `wave/prov-b-routing`
Batch: B (routing + Codex passthrough)

This file maps every contract W1.1–W1.10 (plus the multi-provider scope
extension) pins to the test that covers it, across the smart-coverage matrix
(unit / integration / functional; happy / edge / error). W1 owns the **RED**
half of the tests-first pair: the suite must collect with zero errors and
pass `make lint` + `make typecheck`, with the contract assertions xfailed
(`strict=False`) until W3 (Codex `model_providers` passthrough + shared
multi-provider helper) and W4 (chain semantics) land.

## Design decisions (locked by W1, recorded here so W3 inherits them)

### Env-var naming convention

Indexed multi-provider pairs (canonical):

```
MERGECRAFT_CUSTOM_PROVIDER_API_KEY_<N>   +   MERGECRAFT_CUSTOM_PROVIDER_BASE_URL_<N>
```

where `N >= 1` is an integer index. Both halves must be set for provider `N`
to be present; partial pairs (only one half) are **dropped** — never partial-
written.

Plus the singleton back-compat alias (PR #79 / D7):

```
MERGECRAFT_CUSTOM_PROVIDER_API_KEY       +   MERGECRAFT_CUSTOM_PROVIDER_BASE_URL
```

maps to a single provider id `default` when no indexed pair is set, and is
**ignored** when any indexed pair is present.

### Provider id source of truth

The provider id is `"provider_" + str(N)` for indexed pairs (e.g. `_1` →
`provider_1`, `_2` → `provider_2`), and `default` for the singleton alias.
The id is **deterministic and suffix-derived** — never derived from the base
URL's hostname (hostnames change; indices are stable and grep-friendly).

### Discovery

Enumerate every `os.environ` key matching
`MERGECRAFT_CUSTOM_PROVIDER_(API_KEY|BASE_URL)_\d+`, pair by numeric suffix,
require both halves per index, sort by `N` ascending. **Gaps are preserved**
(no renumbering — `_1` + `_3` set, `_2` absent → providers 1 and 3 present,
2 absent).

### Shared helper signature

`src/mergecraft/agents/openai_compatible_gateways.py` must expose a
multi-provider resolver, in addition to today's singleton
`resolve_gateway_endpoint()`. Acceptable shapes (both pinned by tests):

- `dict[str, ProviderRecord]` keyed by provider id; **or**
- a sequence (`tuple` / `frozenset` / `list`) of `ProviderRecord`.

`ProviderRecord` (or equivalent) must carry at minimum:

| Field          | Purpose                                              |
|----------------|------------------------------------------------------|
| `provider_id`  | `provider_<N>` or `default`                          |
| `base_url`     | resolved value                                       |
| `api_key`      | resolved value (never logged)                        |
| `base_url_env` | env-var name that sourced `base_url` (for redaction) |
| `api_key_env`  | env-var name that sourced `api_key` (for redaction)  |

Both `agents/opencode.py` and `agents/codex.py` must consume the same
helper (D7); codex does NOT today, so the structural assertion is xfailed.

## xfail schedule

| Wave | Test file                                              | Marker reason prefix                                                  |
|------|--------------------------------------------------------|-----------------------------------------------------------------------|
| **W3** | `tests/agents/test_codex_custom_provider.py`         | `green after W3:` for `model_providers` emission + multi-provider shape |
| **W3** | `tests/agents/test_opencode_custom_provider.py` (ext) | `green after W3:` for OpenCode multi-provider shape                    |
| **W3** | `tests/agents/test_openai_compatible_gateways.py`     | `green after W3:` for the shared multi-provider resolver              |
| **W4** | `tests/utils/test_explicit_model_chain.py`            | `green after W4:` for chain semantics (#37)                            |

All cross-wave markers use `strict=False` so an early-passing xfail is an
XFAIL → XPASS upgrade, not a hard failure. W3/W4 reconcile by deleting
markers on tests the implementation now satisfies.

## Structural / regression-pin cases (green from W1, not xfailed)

| #     | Test                                                                | Reason it is structural                                                  |
|-------|---------------------------------------------------------------------|--------------------------------------------------------------------------|
| W1.1a | `test_custom_provider_is_registered_from_env` (existing)            | PR #79 regression pin — singleton helper already works.                  |
| W1.1b | `test_provider_omitted_unless_both_env_vars_are_set` (existing)     | Singleton helper short-circuits to `None` when one half is missing.      |
| W1.1c | `test_provider_omitted_for_an_unprefixed_model` (existing)          | Provider id derivation requires a slash in the model.                    |
| W1.1d | `test_unconfigured_environment_leaves_config_unchanged` (existing)  | No env vars → no provider block; harness contract preserved.            |
| W1.3a | `test_codex_config_toml_has_no_provider_block_without_env`          | Today `write_mcp_config()` writes no provider block — passes green.      |
| W1.1e | `test_opencode_singleton_alone_emits_default_provider_block` (XPASS) | Singleton helper already returns `("default", ...)` when model prefix matches. |

`test_opencode_partial_indexed_pair_is_dropped` and
`test_opencode_indexed_wins_singleton_ignored` xpass vacuously today
(assertions guarded by `isinstance(provider, dict)`); they become real
assertions once W3 lands the multi-provider resolver.

## Contract → test matrix

| #       | Decision / convention                              | Test (this wave)                                                                 | Scenario class                |
|---------|----------------------------------------------------|----------------------------------------------------------------------------------|-------------------------------|
| W1.1a   | PR #79 regression pin (singleton)                  | `test_custom_provider_is_registered_from_env`                                    | structural (regression pin)   |
| W1.1b   | partial singleton pair → no block                  | `test_provider_omitted_unless_both_env_vars_are_set` (parametrized)              | edge case                     |
| W1.1c   | unprefixed model → no block                        | `test_provider_omitted_for_an_unprefixed_model`                                  | edge case                     |
| W1.1d   | no env vars → unchanged                            | `test_unconfigured_environment_leaves_config_unchanged`                          | structural (no-op)            |
| W1.1m   | indexed multi-provider shape                       | `test_opencode_emits_provider_blocks_for_each_indexed_pair`                      | happy path                    |
| W1.1n   | indexed gap preserved                              | `test_opencode_emits_blocks_for_non_contiguous_indices`                          | edge case (gap)               |
| W1.1p   | partial indexed pair dropped                       | `test_opencode_partial_indexed_pair_is_dropped`                                  | edge case (partial)           |
| W1.1q   | singleton alone → `default`                        | `test_opencode_singleton_alone_emits_default_provider_block`                     | edge case (back-compat)       |
| W1.1r   | indexed overrides singleton                        | `test_opencode_indexed_wins_singleton_ignored`                                   | precedence                    |
| W1.2a   | single-provider TOML emission                      | (covered by W1.3a structural test against today's writer)                       | structural                    |
| W1.2b   | two indexed providers → two TOML blocks            | `test_codex_config_toml_writes_both_indexed_providers`                          | happy path                    |
| W1.2c   | N=3 indexed providers → three TOML blocks          | `test_codex_config_toml_writes_three_indexed_providers`                          | happy path (parametrized)     |
| W1.3a   | no env vars → no TOML provider block               | `test_codex_config_toml_has_no_provider_block_without_env`                       | structural                    |
| W1.3b   | partial coverage table                             | `test_codex_partial_indexed_coverage_writes_only_present_providers` (parametrized) | edge cases                    |
| W1.3c   | singleton alone → `default` TOML block             | `test_codex_singleton_alone_emits_default_provider_block`                        | edge case (back-compat)       |
| W1.3d   | indexed overrides singleton                        | `test_codex_indexed_wins_singleton_ignored`                                      | precedence                    |
| W1.4a   | shared helper exposes multi-provider resolver      | `test_shared_helper_exposes_multi_provider_resolver`                             | structural                    |
| W1.4b   | resolver handles indexed pairs                     | `test_shared_multi_provider_resolver_handles_indexed_pairs`                     | happy path                    |
| W1.4c   | resolver preserves gaps                            | `test_shared_multi_provider_resolver_preserves_index_gaps`                       | edge case (gap)               |
| W1.4d   | resolver drops partial pairs                       | `test_shared_multi_provider_resolver_drops_partial_pairs`                        | edge case (partial)           |
| W1.4e   | resolver singleton → `default`                     | `test_shared_multi_provider_resolver_singleton_maps_to_default`                  | edge case (back-compat)       |
| W1.4f   | resolver indexed overrides singleton               | `test_shared_multi_provider_resolver_indexed_overrides_singleton`               | precedence                    |
| W1.4g   | both harnesses import the shared helper            | `test_both_harnesses_consume_the_shared_helper`                                  | structural (D7)               |
| W1.4h   | `ProviderRecord` carries env-var provenance        | `test_provider_record_carries_env_var_provenance`                               | structural (convention 7)     |
| W1.5    | no API key in logs                                 | `test_generated_configs_never_log_either_api_key`                                | error handling (convention 7) |
| W1.6    | explicit model input → chain head + tail preserved | `test_explicit_model_input_preserves_configured_chain_tail`                      | happy path (#37)              |
| W1.7    | explicit-pin opt-in → single-entry chain           | `test_explicit_pin_opt_in_still_yields_single_entry_chain`                      | edge case (escape hatch)      |
| W1.8a   | GHA path walks chain on credential skip            | `test_gha_payload_path_walks_the_chain_credential_skip`                          | integration (D9)              |
| W1.8b   | GHA path walks chain on retryable failure          | `test_gha_payload_path_walks_the_chain_retryable_failure`                        | integration (D9)              |

## Per-decision rationale

### D6 — PR #79 regression pin

`test_custom_provider_is_registered_from_env` (existing, in
`tests/agents/test_opencode_custom_provider.py`) pins the singleton helper's
behaviour. The new tests build on top of it — none deletes or weakens the
singleton contract.

### D7 — Shared resolver + multi-provider

The shared helper in `mergecraft.agents.openai_compatible_gateways` must
expose both the existing singleton `resolve_gateway_endpoint()` AND a new
multi-provider resolver (W3 lands). The structural assertion
`test_both_harnesses_consume_the_shared_helper` (W1.4g) and the typed-
record assertion `test_provider_record_carries_env_var_provenance` (W1.4h)
pin the contract W3 must produce.

### D8 — Chain semantics (#37)

W4 changes the semantics so a supplied `model:` input becomes the **head** of
the effective chain rather than a chain kill-switch. W1.6 / W1.7 / W1.8
pin the contract from three angles: unit (W1.6, W1.7), integration through
`run_with_model_chain` driven by the GHA payload path (W1.8). The exact
surface W4 lands (a `head=` kwarg, a `pin=` opt-in, or something else) is
the W4 implementer's choice — the tests pin the observable contract, not
the signature.

### D9 — Acceptance at the Action boundary

W1.8 drives `run_with_model_chain` with the chain semantics the GHA payload
path will feed it. The asserts are end-to-end: the chain walks across
providers when the first entry is credential-missing or hits a retryable
failure.

### D11 — Convention 7 (no key in logs)

W1.5 captures both stdlib logs (via `caplog`) and loguru output (via a
synthetic sink) and asserts both sentinel keys never appear. Parametrized
across providers in spirit (the test sets two distinct pairs).

## Coverage matrix summary

- **Layer:** unit tests dominate (resolver shapes, env-var discovery,
  per-provider env parsing). Two integration tests cover the GHA payload
  path (W1.8a/b).
- **Scenario classes:**
  - **happy path**: W1.1m, W1.2b, W1.2c, W1.4b, W1.6
  - **edge cases**: W1.1n, W1.1p, W1.1q, W1.3b, W1.3c, W1.4c, W1.4d, W1.4e, W1.7
  - **error handling**: W1.5, W1.8a, W1.8b
  - **structural (regression pins)**: W1.1a, W1.1b, W1.1c, W1.1d, W1.3a, W1.4a, W1.4g, W1.4h
  - **precedence**: W1.1r, W1.3d, W1.4f

## Reconciliation plan

After W3 lands:

1. Drop every `@pytest.mark.xfail(reason="green after W3: …", strict=False)`
   marker on tests the implementation now satisfies.
2. Keep the structural tests (the W1.1 single-provider regression pin).
3. Reconcile the multi-provider shape: if W3 lands a `dict` (the preferred
   shape), no test changes; if W3 lands a sequence, the
   `_coerce_to_dict` helper in `test_openai_compatible_gateways.py`
   already accepts both.
4. Update this file's xfail schedule to record which wave turned each xfail
   green.

After W4 lands:

1. Drop every `green after W4:` marker on tests now satisfied.
2. Re-evaluate `test_explicit_pin_opt_in_still_yields_single_entry_chain`
   if W4 lands a different pin surface (today the test parametrizes a
   `pin=` kwarg; W4 may land an input or config-key).

## Open questions for W3

- Should the singleton `MERGECRAFT_CUSTOM_PROVIDER_*` keys also be allowed
  as a fallback for `provider_1` when only the singleton is set, or
  strictly map to a separate `default` id? **Recommend the latter** —
  cleaner separation; tests pin it as such.
- For the typed `ProviderRecord`, should the env-var names be exposed as
  attributes (record.base_url_env, record.api_key_env) or as a nested dict?
  **Recommend attributes** — keeps the call sites short.

## Notes

- No `src/` or production-doc edits in this wave; the test plan lives at
  `docs/test-plans/issues-provider-routing.md` and is **tracked** in this
  repo (not gitignored — confirmed at wave time).
- The W1 work does not touch the primary checkout's
  `.ignorelocal/waves/issues-provider-routing-wave-plan.md` — that copy is
  the planning ledger and is updated via `cp` sync after the W1 commit
  lands.
- All env-var naming derives from the operator-locked convention; W3 must
  not invent a third mechanism (D7).
