# Open issues sweep 2026-08-22b — Batch GC test plan

Maps **W5 RED** contracts for #404 to the test suite. Source plan:
`.ignorelocal/waves/open-issues-sweep-2026-08-22b-wave-plan.md`.

## D8 — `_blob_ref()` resolution (#404) → W6

| Contract | Tests | Layer |
| --- | --- | --- |
| `DEFAULT_BLOB_REF` is `pre-0.0.1` | `tests/docs/test_gen_agent_packages_blob_ref.py::test_default_blob_ref_constant_is_pre_0_0_1` | unit |
| `MERGECRAFT_AGENT_PACKAGES_REF` env override wins | `…::test_blob_ref_uses_env_override` | unit |
| Missing `v0.1.0a1` tag → default, not pin | `…::test_blob_ref_returns_default_when_pin_tag_missing` | unit |
| Present pin tag → `action_pin_minimal()` | `…::test_blob_ref_uses_action_pin_minimal_when_tag_exists` | unit |

## xfail reconciliation

| Wave greens | Remove xfail from |
| --- | --- |
| W6 | `test_default_blob_ref_constant_is_pre_0_0_1`, `test_blob_ref_returns_default_when_pin_tag_missing`, `test_blob_ref_uses_action_pin_minimal_when_tag_exists` |

## Verification commands

```bash
make lint
make typecheck
uv run pytest --collect-only -q tests/docs/test_gen_agent_packages_blob_ref.py
uv run pytest -q tests/docs/test_gen_agent_packages_blob_ref.py  # green since W6 (808763ce)
```

## W5 evidence (2026-08-22 ✅: 808763ce)

- `scripts/gen_agent_packages.py` uses `DEFAULT_BLOB_REF = "pre-0.0.1"` and `_blob_ref()` falls back
  when `action_pin_minimal()` tag is absent (`mergecraft.utils.git_ref.git_ref_exists`).
- `git rev-parse --verify refs/tags/v0.1.0a1^{commit}` fails on this checkout (G1 tag not cut).
- `pre-0.0.1` branch resolves locally.
