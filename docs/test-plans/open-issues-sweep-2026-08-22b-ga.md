# Open issues sweep 2026-08-22b — Batch GA test plan

Maps **W1 RED** contracts for #402 + #414 to the test suite. Source plan:
`.ignorelocal/waves/open-issues-sweep-2026-08-22b-wave-plan.md`.

## D7 — checkout vs packaged `defaults.yaml` (#402, #414) → W2

| Contract | Tests | Layer |
| --- | --- | --- |
| Checkout and packaged copies are byte-identical | `tests/pins/test_defaults_yaml_sync.py::test_checkout_and_packaged_defaults_yaml_are_byte_identical` | unit |
| `make pins-check` target exists | `…::test_make_pins_check_target_exists` | integration |
| `pins-check` in `CI_STEPS` | `…::test_make_pins_check_in_ci_steps` | integration |
| `pins-check` in `ci-static` prerequisites | `…::test_make_pins_check_in_ci_static` | integration |

## xfail reconciliation

| Wave greens | Remove xfail from |
| --- | --- |
| W2 | all tests in `tests/pins/test_defaults_yaml_sync.py` |

## Verification commands

```bash
make lint
make typecheck
uv run pytest --collect-only -q tests/pins/test_defaults_yaml_sync.py
uv run pytest -q tests/pins/test_defaults_yaml_sync.py  # green since W2 (808763ce)
```

## W1 evidence (2026-08-22)

- Packaged copy differs on line 2 comment (`diff` shows checkout `# Edit here…` vs packaged `# Checkout copy…`).
- `pins-check` target and `CI_STEPS` / `ci-static` wiring absent on base `bc76b1dc`.
