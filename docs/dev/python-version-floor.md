# Python version floor — ADR (#343, option A)

**Status:** Accepted (option A in progress; option B deferred)
**Date:** 2026-08-20
**Issue:** [#343](https://github.com/alexhawat/mergeCraft/issues/343)

## Context

mergeCraft currently declares `requires-python = ">=3.14"` in `pyproject.toml`.
That floor was chosen while the codebase used PEP 758 bare multi-type except
syntax (`except A, B:`), which is invalid on Python 3.11–3.13. Lowering the
install floor widens who can run the CLI and Action locally without changing
review behaviour.

Issue #343 proposes two paths:

| Option | Summary |
|--------|---------|
| **A** | Parenthesize PEP 758 except groups, audit other 3.14-only APIs, lower `requires-python` to `>=3.11`, widen CI |
| **B** | Ship a standalone binary (PyOxidizer / PEX / similar) |

## Decision

**Option A now, option B later** (plan D8).

1. **Parenthesize** every multi-type `except` under `src/mergecraft/` as
   `except (A, B):` — behaviour-neutral, no semantic change.
2. **Audit** for other 3.14-only constructs (`annotationlib`, PEP 750
   t-strings, …). W12 found none beyond bare except tuples.
3. **Lower** `requires-python` to `>=3.11` and run CI on 3.11 + 3.14 (W14).
4. **Do not** add PyOxidizer, standalone, or PEX bundling in this program.
5. **Do not** claim PyPI is published until Craft actually ships `merge-craft`.

Files actively edited on the parallel `open-issues-sweep-2026-08-19e` branch
may defer parenthesization until that work merges; note any skips in the AF
batch commit message.

## Consequences

- **Positive:** Stock Python 3.11+ installs via `uv` / venv; Docker image
  remains available for pinned environments.
- **Positive:** CI catches 3.11 syntax regressions before release.
- **Neutral:** Option B (standalone binary) becomes a **follow-up GitHub
  issue** filed at batch AF Final — not blocked on A, but not implemented here.
- **Negative:** Contributors must parenthesize new multi-type except handlers;
  the W12 inventory test guards this until the floor lands.

## Implementation waves

| Wave | Deliverable |
|------|-------------|
| W12 | RED inventory (27 files / 44 sites) + 3.14-ism audit |
| W13 | This ADR + parenthesize except (skip 19e-active `analyzers/*.py` if needed) |
| W14 | `requires-python >= 3.11`, CI matrix, `docs/distribution.md` + README install copy |
| AFF | Draft-close #343; file new issue for option B |

## References

- Wave plan: `.ignorelocal/waves/open-issues-sweep-2026-08-20-wave-plan.md`
- Tests: `tests/test_python_version_floor_af.py`
- Test plan: `docs/test-plans/open-issues-sweep-2026-08-20-af.md`
