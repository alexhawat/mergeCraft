# #57 — Nous Research / DeepSeek V4 Flash — W1 RED test plan

Wave plan: `.ignorelocal/waves/issues-nous-deepseek-v4-flash-wave-plan.md`
Worktree: `mergecraft-issue-57-nous` @ `wave/issue-57-nous`
Batch: A (feature, #57)

This file maps every contract W1.1–W1.18 pins to the test that covers it,
across the smart-coverage matrix (unit / integration / functional;
happy / edge / error). W1 owns the **RED** half of the tests-first pair:
the suite must collect with zero errors and pass `make lint` +
`make typecheck`, with the contract assertions xfailed (`strict=False`)
until W2 lands `src/mergecraft/cli/auth_cmd.py::auth_nous`,
`src/mergecraft/utils/agent_resolve.py::_has_nous_auth`, and
`src/mergecraft/models.py::PROVIDERS["nous"]`.

The W0 finding that shapes the validator tests: the Nous Portal's
`GET /v1/models` is a public catalogue that returns 200 even for an invalid
bearer, so the W2 validator MUST probe `POST /v1/chat/completions` (with
a minimal body, `model: deepseek/deepseek-v4-flash`, empty `messages: []`)
to exercise the 401/403 reject branch. W1.14 + W1.12 / W1.13 are written
against that probe path; the `auth --help` collection smoke (W1.18) pins
the subcommand registration separately.

## xfail schedule

| Wave   | Test file                                          | Marker reason prefix                                                 |
|--------|----------------------------------------------------|----------------------------------------------------------------------|
| **W2** | `tests/agents/test_agent_resolve_nous.py`          | `green after W2:` for the catalog + credential + binary-gate cases    |
| **W2** | `tests/cli/test_auth_nous_cmd.py`                  | `green after W2:` for the subcommand + validator cases                |
| **W2** | `tests/cli/test_models_list_nous.py`               | `green after W2:` for the catalog row cases                           |

All cross-wave markers use `strict=False` so an early-passing xfail is an
XFAIL → XPASS upgrade, not a hard failure. W2 reconciles by deleting
markers on tests the implementation now satisfies.

## Structural / regression-pin cases (green from W1, not xfailed)

| #     | Test                                                                | Reason it is structural                                                            |
|-------|---------------------------------------------------------------------|------------------------------------------------------------------------------------|
| W1.2  | `test_get_model_provider_for_nous_slug`                             | `parse_model` already splits on the first slash; no catalog knowledge required.     |
| W1.5  | `test_has_credentials_for_slug_nous_with_no_keys`                   | Provider arm is unimplemented; falls through to `return False` already.            |
| W1.7  | `test_agent_binary_available_does_not_require_nous_on_path`         | `binary_by_provider.get("nous")` returns `None`; the function already short-circuits.|
| W1.8  | `test_build_custom_provider_block_written_for_nous_slug`            | Regression pin for PR #79; the block is already written today.                     |
| W1.15 | `test_no_real_api_call_in_unit_tests` (×2 files)                    | Property tests on the test corpus itself, not on the implementation.                |
| W1.18 | `test_models_list_help`, `test_auth_nous_subcommand_is_collectable` | Collection smoke. The auth subcommand smoke is xfailed because the subcommand does not exist yet; the models list help is structural. |

`test_auth_nous_subcommand_is_collectable` is marked xfail because it
cannot be green until W2 registers the subcommand — the plan's W1.17 list
of structural cases is correct in spirit but this one only becomes
structural after W2. W2 reconciles by dropping the marker.

## Contract → test matrix

| #       | Decision / convention                  | Test (this wave)                                                 | Scenario class                |
|---------|----------------------------------------|------------------------------------------------------------------|-------------------------------|
| W1.1    | D6 — `PROVIDERS["nous"]` + ModelDef    | `test_nous_provider_in_providers_and_aliases`                    | happy path (catalog presence) |
| W1.2    | structural                             | `test_get_model_provider_for_nous_slug`                          | structural (parser)           |
| W1.3    | D4 — `NOUS_API_KEY` first-class        | `test_has_credentials_for_slug_nous_with_nous_api_key`            | happy path                    |
| W1.4    | D4 — `MERGECRAFT_CUSTOM_PROVIDER_API_KEY` alias | `test_has_credentials_for_slug_nous_with_only_custom_provider_alias` | edge case (back-compat)       |
| W1.5    | D-table fail-loud                      | `test_has_credentials_for_slug_nous_with_no_keys`                | structural (no creds → False) |
| W1.6    | D5 — runnable with creds only          | `test_is_runnable_model_slug_nous_with_credentials`              | happy path                    |
| W1.7    | D5 — no `shutil.which("nous")`         | `test_agent_binary_available_does_not_require_nous_on_path`      | structural                    |
| W1.8    | PR #79 regression pin                  | `test_build_custom_provider_block_written_for_nous_slug`         | structural                    |
| W1.9    | catalog row + credentials marker       | `test_mergecraft_models_list_renders_nous_row_{with,without}_credentials` | happy path + edge case |
| W1.10   | D7 — getpass + validate + gh secret    | `test_auth_nous_prompts_with_getpass_and_writes_secret`          | happy path                    |
| W1.11   | D7 — gh-unauthenticated fail-closed    | `test_auth_nous_fails_closed_when_gh_is_unauthenticated`         | error handling                |
| W1.12   | D7 — 401/403 reject                    | `test_auth_nous_rejects_on_401_or_403`                           | error handling                |
| W1.13   | D7 — network warn-and-save             | `test_auth_nous_warns_and_saves_on_network_error`                | error handling                |
| W1.14   | D7 — validator unit table              | `test_auth_nous_validator_returns_correct_status` (parametrised) | edge / error (200/401/403/500/502) |
| W1.14b  | D7 — validator network warning        | `test_auth_nous_validator_warns_and_returns_true_on_network_error` | error handling              |
| W1.15   | convention 7 — no real network in unit | `test_no_real_api_call_in_unit_tests` (×2 files)                 | structural                    |
| W1.16a  | D8 — chain selection                  | `test_invoke_smoke_nous_slug_is_selectable_via_chain`            | integration (chain)           |
| W1.16b  | D8 — real Portal probe                 | `test_auth_nous_real_portal_probe_round_trip`                    | integration (validator)       |
| W1.18   | collection smoke                       | `test_models_list_help`, `test_auth_nous_subcommand_is_collectable` | structural / collection    |

## Per-decision rationale

### D4 — Auth precedence (`NOUS_API_KEY` > `MERGECRAFT_CUSTOM_PROVIDER_API_KEY`)

W1.3 and W1.4 split the precedence into two parametrized cases: each env
var set independently must satisfy `has_credentials_for_slug`. W1.5
clears both and asserts `False`. Together they pin the docstring
contract that W2's `_has_nous_auth` must carry.

### D5 — `nous` has no required CLI

W1.7 stubs `shutil.which` to always return `None` and asserts
`_agent_binary_available("nous/...")` still returns `True`. W1.6
composes the credential + binary gates into `is_runnable_model_slug`
returning `True`. W2.4 makes the `"nous": None` entry in
`binary_by_provider` explicit; the test guards against a refactor that
silently reintroduces a `shutil.which("nous")` lookup.

### D6 — Catalog entry

W1.1 asserts `PROVIDERS["nous"]` and the row in `MODEL_ALIASES`. It also
drives `tests/test_models.py::test_providers_include_expected_keys`
forward — W2 must extend that `expected` set to include `"nous"`. The
W2 commit is the single source of that extension; W1 only pins the
contract.

### D7 — Auth subcommand shape

W1.10 mirrors the gemini cursor template: getpass → validate →
`gh secret set NOUS_API_KEY --repo <owner>/<repo>`. W1.11 fails closed
when `_get_gh_token` raises (convention 7 — never assert on the token
value, only on the destination). W1.12 / W1.13 cover the 401/403
reject and the network warn-and-save branches through
`httpx.MockTransport` — no real call to `inference-api.nousresearch.com`
from this file. W1.14 is the parametrised unit table for the validator:
200 → True, 401/403 → False, 500/502 → True with a captured `logger.warning`.

The validator's probe is `POST https://inference-api.nousresearch.com/v1/chat/completions`
with `Authorization: Bearer <key>` and a minimal body
(`{"model": "deepseek/deepseek-v4-flash", "messages": []}`). The handler
asserts the path matches `/v1/chat/completions` and the Authorization
header is set; if W2 implements against `/v1/models` instead, every
parametrised case would still pass for the wrong reason (W0.4 finding:
the catalogue is unauthenticated).

### D8 — Integration-marked real-invocation smoke

W1.16a (`test_invoke_smoke_nous_slug_is_selectable_via_chain`) and W1.16b
(`test_auth_nous_real_portal_probe_round_trip`) are marked
`@pytest.mark.integration`. They self-skip when `NOUS_API_KEY` is unset
in the test environment and are excluded from `make test` via the
`-m "not integration"` filter that `make test` already applies.

## Coverage matrix summary

- **Layer:** unit tests dominate (catalog, validator, getpass, gh secret
  call shape, error handling). Integration tests cover the chain
  selection path and the real Portal probe; both are gated.
- **Scenario classes:**
  - happy path: W1.1, W1.3, W1.6, W1.9, W1.10
  - edge cases: W1.4, W1.9-with-creds, W1.14[200-True]
  - error handling: W1.5, W1.11, W1.12, W1.13, W1.14[401/403/500/502]
  - structural: W1.2, W1.7, W1.8, W1.15, W1.18
  - integration: W1.16a, W1.16b

## Reconciliation plan (W2)

After W2 lands `auth_nous`, `_has_nous_auth`, and the `nous` provider
entry in `PROVIDERS`:

1. Drop every `@pytest.mark.xfail(reason="green after W2: ...", strict=False)`
   marker on tests the implementation now satisfies.
2. `test_auth_nous_subcommand_is_collectable` becomes structural (the
   subcommand is registered); remove the xfail marker so a future
   regression that silently drops the subcommand trips the test.
3. Keep the structural tests (`test_no_real_api_call_in_unit_tests`,
   `test_get_model_provider_for_nous_slug`, the regression pin
   `test_build_custom_provider_block_written_for_nous_slug`).
4. Extend `tests/test_models.py::test_providers_include_expected_keys`
   with `"nous"` in the `expected` set (W2.1's parallel edit).
5. Update this file's xfail schedule to record the wave that turned
   each xfail green (W2 for this batch).

## Notes

- All network access in unit tests goes through `httpx.MockTransport`;
  the production Portal URL appears once per file as a typed constant
  and the `test_no_real_api_call_in_unit_tests` structural guard
  enforces that cap.
- The validator direct tests (`test_auth_nous_validator_*`) and the
  integration-marked smoke (`test_auth_nous_real_portal_probe_round_trip`)
  each assume `httpx` will call `POST /v1/chat/completions` and never
  call the catalogue. If W2 surfaces a reason to probe both endpoints,
  the validator tests must be re-evaluated; this plan does not assume
  that change.
- No `src/` or production-doc edits in this wave; the test plan lives
  at `docs/test-plans/issues-57-nous-deepseek-v4-flash.md` and is **not**
  gitignored (`docs/test-plans/` is the tracked test-doc root).
- The W1 work does not touch the primary checkout's
  `.ignorelocal/waves/issues-nous-deepseek-v4-flash-wave-plan.md` — that
  copy is the planning ledger and is updated in the wave close-out step
  after the W1 commit lands.
