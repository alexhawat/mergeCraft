# Provider harness (test-only)

Deterministic provider and agent-protocol testing lives under `tests/support/provider_harness/`
with RED/GREEN suites in `tests/harness/`. This is **not** the production `harness:` agent driver.

## Writing a fixture

1. Add JSON under `tests/harness/fixtures/<scenario>.json` (see `schema-smoke.json`).
2. Match fields: `provider`, `model`, optional `streaming`, `turn_index`, tool-state guards.
3. Response: `body` **or** ordered `blocks` (text / tool_call).

Load in tests:

```python
from tests.support.provider_harness.pytest_plugin import load_harness_fixtures

provider_harness.reload(load_harness_fixtures("no-findings"))
```

## Pytest fixture

`provider_harness` (auto-loaded via `tests/conftest.py`) starts a local OpenAI-compatible stub on
`127.0.0.1:0`, patches `MERGECRAFT_CUSTOM_PROVIDER_{BASE_URL,API_KEY}` before client construction,
and tears the server down after each test. Dummy key: `sk-mergecraft-test`.

## Named failure profiles

Set `"profile"` on a fixture: `http_429`, `http_500`, `http_401`, `timeout`, `malformed_json`,
`empty_stream`, `disconnect_after_chunk`. Profiles feed existing mergeCraft classifiers — the harness
does not implement its own retry loop.

## Recording (local only)

```bash
export MERGECRAFT_PROVIDER_HARNESS_RECORD=1
```

Writes sanitized JSON under `.ignorelocal/provider-harness/records/`. Inspect manually; copy into
`tests/harness/fixtures/` only after review. Never auto-commit.

## Strict matching

Default is strict (`match_fixture(..., strict=True)`). Lenient mode exists locally via
`MERGECRAFT_PROVIDER_HARNESS_LENIENT=1` — never set in CI or `tests/conftest.py`.
