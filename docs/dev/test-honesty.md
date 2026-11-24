# Test honesty lint

Coding agents sometimes make CI green without fixing real failures. mergeCraft
runs mechanical **test honesty** checks on the `tests/` tree (including
`conftest.py` files) to block common shortcuts.

## Ruff (tests only)

`make lint-test-honesty` runs Ruff on `tests/` with:

- **S110** — `try` / `except` / `pass` (silent exception swallowing)
- **SIM105** — prefer `contextlib.suppress` over empty `except` (same class of bug)

## AST checker

`scripts/lint_test_honesty.py` flags:

| Rule | What it catches | Fix |
|------|-----------------|-----|
| `sleep_constant` | `time.sleep(<literal>)` / `asyncio.sleep(<literal>)` in tests or fixtures | Await the event or poll the real signal instead of sleeping |
| `flake_marker` | `@pytest.mark.flaky` | Fix root instability instead of rerunning |
| `rerun_config` | `reruns=`, `pytest_rerunfailures` | Same as flaky markers |
| `timeout_inflated` | `@pytest.mark.timeout(N)` with `N > 180` | Speed up the test or split it; do not raise the budget |
| `except_swallow` | `except ...: pass` in tests | Assert expected failures or re-raise |
| `conditional_assert` | `assert` only under `if` / loops / `try` (conservative) | Assert unconditionally or use `pytest.raises` |
| `self_mock` (warning) | `patch("mergecraft.<module-under-test>...")` from matching `test_<mod>.py` | Patch collaborators, not the unit under test |

Grandfathered hits live in `scripts/test_honesty_baseline.json`. **New** violations
fail `make lint` and pre-commit.

## Suppressions

When a pattern is genuinely required, add on the same line or the line above:

```python
time.sleep(0.05)  # honesty: allow subprocess teardown race
```

The reason after `allow` is mandatory. Prefer fixing the test over suppressing.

## Commands

```bash
make lint-test-honesty
uv run python scripts/lint_test_honesty.py --skip-ruff   # AST only (tests)
uv run pytest tests/scripts/test_lint_test_honesty.py -q
```

Maintainers regenerating the baseline (after fixing bulk debt):

```bash
uv run python scripts/lint_test_honesty.py --write-baseline --skip-ruff
```