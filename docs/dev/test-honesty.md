# Test honesty lint

Coding agents sometimes make CI green without fixing real failures. mergeCraft
runs mechanical **test honesty** checks on the `tests/` tree (including
`conftest.py` files) to block common shortcuts.

## Ruff (tests only)

`make lint-test-honesty` runs Ruff on `tests/` with **S110** (`try` / `except` /
`pass`). **SIM105 is not enabled** — its autofix replaces `pass` with
`contextlib.suppress`, which would satisfy Ruff while keeping the same silent
swallow. The AST checker flags both `except: pass` and `contextlib.suppress`.

Checker fixtures under `tests/scripts/fixtures/test_honesty/` are excluded from
the Ruff pass (and from repo-wide AST walks) but can be scanned when passed
explicitly to unit tests.

## AST checker

`scripts/lint_test_honesty.py` flags:

| Rule | What it catches | Fix |
|------|-----------------|-----|
| `sleep_constant` | `time.sleep(<literal>)` / `asyncio.sleep(<literal>)` in tests or fixtures | Await the event or poll the real signal instead of sleeping |
| `flake_marker` | `@pytest.mark.flaky` | Fix root instability instead of rerunning |
| `rerun_config` | `reruns=`, `pytest_rerunfailures` | Same as flaky markers |
| `timeout_inflated` | `@pytest.mark.timeout(N)` with `N > 180` | Speed up the test or split it; do not raise the budget |
| `except_swallow` | `except ...: pass` or `contextlib.suppress` in tests | Assert expected failures or re-raise |
| `conditional_assert` | `assert` only under `if` / loops / `try` (not `with`) | Assert unconditionally or use `pytest.raises` |
| `self_mock` (warning) | `patch("mergecraft.<module-under-test>...")` from matching `test_<mod>.py` | Patch collaborators, not the unit under test |

`sleep_constant` ignores `sleep(0)` / `sleep(0.0)` (common `asyncio` yield).

Grandfathered hits live in `scripts/test_honesty_baseline.json`. Each entry is
`path:rule:anchor` where **anchor** is derived from the offending construct
(function name, sleep literal, patch target, assert digest, etc.) — not the line
number — so harmless line edits do not reopen baselined debt.

**New** violations fail `make lint` and pre-commit.

## Suppressions

When a pattern is genuinely required, add on the same line or the line above:

```python
time.sleep(0.05)  # honesty: allow subprocess teardown race
```

The reason after `allow` is mandatory. Prefer fixing the test over suppressing.
S110 sites need a real fix or `# noqa: S110` with justification; the honesty
allow comment does not apply to Ruff.

## Commands

```bash
make lint-test-honesty
uv run python scripts/lint_test_honesty.py --skip-ruff   # AST only (tests)
uv run pytest tests/scripts/test_lint_test_honesty.py -q
```

Maintainers only:

```bash
# Drop fingerprints for violations that were actually fixed (does not add new ones)
uv run python scripts/lint_test_honesty.py --prune-baseline --skip-ruff
# Full rewrite after deliberate bulk cleanup (never to hide new debt on a PR)
uv run python scripts/lint_test_honesty.py --write-baseline --skip-ruff
```