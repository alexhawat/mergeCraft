# Open issues sweep 2026-08-20 — Batch AF test plan (#343)

Wave plan: `.ignorelocal/waves/open-issues-sweep-2026-08-20-wave-plan.md`
Worktree: `../mergecraft-open-issues-sweep-2026-08-20` @ `wave/open-issues-sweep-2026-08-20`
Authoring wave: **W12** (Batch AF RED) · Implementation: **W13–W14** (parenthesize + floor)

## xfail schedule

| Wave | Test | Marker reason | Status |
|------|------|---------------|--------|
| **W13/W14** | `test_af_no_unparenthesized_except_under_src` | `green after W13/W14: PEP 758 parenthesize + 3.11 floor` | pending — **XFAIL** (27 files / 44 sites) |
| **W13/W14** | `test_af_src_compiles_under_python_311_syntax` | `green after W13/W14: PEP 758 parenthesize + 3.11 floor` | pending — **XFAIL** (static scan; no `python3.11` on PATH @ W12) |
| **W14** | `test_af_pyproject_requires_python_floor_is_311` | `green after W13/W14: PEP 758 parenthesize + 3.11 floor` | pending — **XFAIL** (`requires-python = ">=3.14"`) |

## Contract matrix

| # | Contract | Layer | Scenario | Primary test |
|---|----------|-------|----------|--------------|
| AF343a | Zero unparenthesized PEP 758 ``except A, B:`` under ``src/mergecraft/`` | unit | lint guard | `tests/test_python_version_floor_af.py::test_af_no_unparenthesized_except_under_src` |
| AF343b | ``src/mergecraft/**/*.py`` compiles on Python 3.11 | unit | syntax | `test_af_src_compiles_under_python_311_syntax` |
| AF343c | No blocking 3.14-only APIs (``annotationlib``, PEP 750 t-strings) | unit | audit | `test_af_no_python_314_only_apis_block_floor` |
| AF343d | ``pyproject.toml`` ``requires-python = ">=3.11"`` after audit | unit | packaging | `test_af_pyproject_requires_python_floor_is_311` |
| AF343e | Scanner accepts parenthesized / single-type handlers | unit | parametrized | `test_find_unparenthesized_except_violations_parametrized` |
| AF343f | W12 inventory baseline documented | unit | snapshot | `test_af_w12_inventory_baseline_file_and_site_counts` |

## W12 inventory (unparenthesized ``except A, B:``)

**Counts @ AEF:** **27 files**, **44 sites** under `src/mergecraft/`.

| File | Sites |
|------|------:|
| `mergecraft/agents/_stream_consumer.py` | 1 |
| `mergecraft/agents/codex.py` | 1 |
| `mergecraft/analyzers/agentsec/mcp_manifest.py` | 1 |
| `mergecraft/analyzers/config.py` | 1 |
| `mergecraft/analyzers/detect.py` | 1 |
| `mergecraft/analyzers/impact.py` | 2 |
| `mergecraft/analyzers/parsers/osv_json.py` | 1 |
| `mergecraft/analyzers/paths.py` | 1 |
| `mergecraft/analyzers/supply_chain.py` | 1 |
| `mergecraft/cli/auth_cmd.py` | 9 |
| `mergecraft/cli/init_cmd.py` | 1 |
| `mergecraft/cli/tracing_gh_visibility.py` | 1 |
| `mergecraft/cli/watch_cmd.py` | 2 |
| `mergecraft/evals/benchmark.py` | 2 |
| `mergecraft/evals/scoring.py` | 3 |
| `mergecraft/prep/node.py` | 1 |
| `mergecraft/tracing/_tool_attrs.py` | 1 |
| `mergecraft/tracing/exporters.py` | 1 |
| `mergecraft/tracing/otel_bridge.py` | 1 |
| `mergecraft/tracing/redaction.py` | 1 |
| `mergecraft/utils/git_setup.py` | 4 |
| `mergecraft/utils/instructions.py` | 1 |
| `mergecraft/utils/memory.py` | 1 |
| `mergecraft/utils/run_cache.py` | 1 |
| `mergecraft/utils/source_resolve.py` | 2 |
| `mergecraft/utils/workspace.py` | 1 |
| `mergecraft/yes/__init__.py` | 1 |

Note: `mergecraft/review_checks.py` mentions bare except in a **docstring only** — not counted (no AST handler).

## W12 3.14-ism audit notes

| Construct | Result @ W12 |
|-----------|--------------|
| **`annotationlib`** imports / usage | **none** under `src/mergecraft/` |
| **PEP 750 t-strings** (`t"…"`) | **none** — `${t("…")}` prompt placeholders in `modes/*.py` are strings, not t-string syntax |
| **Unparenthesized PEP 758 except** | **27 files / 44 sites** — primary blocker; W13 parenthesizes |
| **`requires-python`** | still `>=3.14` in `pyproject.toml` — W14 lowers after audit |

Audit is **clean for non-except 3.14-isms**; lowering the floor is blocked only by PEP 758 bare tuples until W13 lands.

## W12 notes

- **#343 RED (option A only):** D8 locks parenthesize + audit + `>=3.11` floor; standalone binary (B) is out of scope.
- **Scanner:** `find_unparenthesized_except_violations()` uses AST + source-line check (3.14 parses both forms as `Tuple`).
- **3.11 compile pin:** uses `python3.11 -m py_compile` when on PATH; otherwise the static PEP 758 inventory (same failure surface on 3.14 hosts).
- **D6:** no `analyzers/catalog/**` edits in W12 (tests only).

## Acceptance (W12)

- New tests collect with zero import errors
- `make lint` + `make typecheck` clean on touched paths
- Three contract tests **XFAIL** until W13/W14; inventory snapshot + 3.14 audit + scanner parametrization pass
- No `src/` edits; no D6 paths
