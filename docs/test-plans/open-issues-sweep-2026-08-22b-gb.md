# Open issues sweep 2026-08-22b — Batch GB test plan

Maps **W3 RED** contracts for #403 to the test suite. Source plan:
`.ignorelocal/waves/open-issues-sweep-2026-08-22b-wave-plan.md`.

## D9 — lazy Harbor `DEFAULT_INSTALL_REF` (#403) → W4

| Contract | Tests | Layer |
| --- | --- | --- |
| Importing `mergecraft.harbor.agent` does not call `action_pin_minimal()` | `tests/harbor/test_agent.py::test_import_harbor_agent_does_not_resolve_pin` | unit |
| Lazy accessor `_default_install_ref()` mirrors `init_cmd._workflow_template` | `…::test_default_install_ref_accessor_calls_action_pin_minimal` | unit |
| `install()` resolves default ref via `action_pin_minimal()` when env unset | `…::test_install_resolves_default_ref_via_action_pin_minimal` | integration |
| Default ref pins a release tag (regression) | `…::test_default_install_ref_pins_a_release_tag_not_a_moving_branch` | unit |

## xfail reconciliation

| Wave greens | Remove xfail from |
| --- | --- |
| W4 | `test_import_harbor_agent_does_not_resolve_pin`, `test_default_install_ref_accessor_calls_action_pin_minimal`, `test_install_resolves_default_ref_via_action_pin_minimal` |

## Verification commands

```bash
make lint
make typecheck
uv run pytest --collect-only -q tests/harbor/test_agent.py
uv run pytest -q tests/harbor/test_agent.py  # expect 3 XFAIL until W4
```

## W3 evidence

- `harbor/agent.py:22` eagerly assigns `DEFAULT_INSTALL_REF = action_pin_minimal()` at import.
- `init_cmd._workflow_template()` already defers the same call (D9 mirror target).
