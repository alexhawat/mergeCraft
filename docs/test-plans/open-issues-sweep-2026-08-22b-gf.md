# Open issues sweep 2026-08-22b — Batch GF test plan

Maps **W11 RED** contracts for #405 to the test suite. Source plan:
`.ignorelocal/waves/open-issues-sweep-2026-08-22b-wave-plan.md`.

## D12 — `tests/docs/support.py` (#405) → W12

| Contract | Tests | Layer |
| --- | --- | --- |
| `tests.docs.support` importable | `tests/docs/test_support.py::test_support_module_is_importable` | unit |
| `git_ref_exists(ref)` resolves tags/branches/SHAs | `…::test_support_exports_git_ref_exists` | unit |
| `git_ref_exists` shallow-checkout SHA fetch | `…::test_git_ref_exists_fetches_shallow_checkout_sha` | unit |
| `action_uses_pattern` shared regex (case-insensitive) | `…::test_support_exports_action_uses_pattern` | unit |
| `ci_steps()` parses Makefile `CI_STEPS` | `…::test_support_exports_ci_steps` | integration |
| `load_script_module(path)` loads repo scripts | `…::test_support_exports_load_script_module` | integration |
| `load_script_module` accepts repo-relative paths | `…::test_load_script_module_accepts_relative_path` | unit |
| Listed modules import shared helpers (no local dupes) | `…::test_migration_module_imports_shared_support[*]` | integration |
| Existing `tests/docs/test_*.py` still collect | `…::test_docs_contract_modules_still_collect[*]` | smoke |

### Dedup patterns (#405) → W12 migration targets

| Pattern | Current locations | Shared export |
| --- | --- | --- |
| `_git_ref_exists()` | `test_landing_readme.py`, `test_agent_surfaces.py` | `git_ref_exists` |
| `_ACTION_USES` regex | `test_landing_readme.py`, `test_docs_gate.py`, `test_agent_surfaces.py` | `action_uses_pattern` |
| `load_harness_manifest()` / `makefile_prerequisite_tokens()` shared exports | `tests/docs/support.py` | `load_harness_manifest`, `makefile_prerequisite_tokens` |
| `importlib.util` script loading | `test_cli_examples.py`, `test_agent_packages.py`, `test_docs_gate.py`, `test_gen_agent_packages_blob_ref.py`, `test_reference_docs.py` | `load_script_module` |

## xfail reconciliation

| Wave greens | Remove xfail from |
| --- | --- |
| W12 | all `xfail` tests in `tests/docs/test_support.py` except `test_docs_contract_modules_still_collect` (stays green) |

## Verification commands

```bash
make lint
make typecheck
uv run pytest --collect-only -q tests/docs/
uv run pytest -q tests/docs/test_support.py  # green since W12 (808763ce)
```

## W11 evidence (2026-08-22 ✅: ec6390c4)

- `tests/docs/support.py` absent on base `6c135d27` (D12: W12 creates the module).
- Four helper patterns duplicated across ~8 `tests/docs/test_*.py` modules per #405.
- `tests/ci/workflow_support.py` exists for CI workflow YAML only — docs-contract helpers belong in `tests/docs/support.py` (D12).
