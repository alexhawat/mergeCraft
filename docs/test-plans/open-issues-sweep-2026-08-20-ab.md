# Open issues sweep 2026-08-20 — Batch AB test plan (#348)

Wave plan: `.ignorelocal/waves/open-issues-sweep-2026-08-20-wave-plan.md`
Worktree: `../mergecraft-open-issues-sweep-2026-08-20` @ `wave/open-issues-sweep-2026-08-20`
Authoring wave: **W4** (Batch AB RED) · Implementation: **W5** (#348 `_optional_float`)

## xfail schedule

| Wave | Test | Marker reason | Status |
|------|------|---------------|--------|
| **W5** | `test_model_params_from_mapping_ignores_non_finite_float_fields[float_nan_inf]` | `green after W5: _optional_float isfinite` | pending — **XFAIL** |
| **W5** | `test_model_params_from_mapping_ignores_non_finite_float_fields[string_nan_inf]` | `green after W5: _optional_float isfinite` | pending — **XFAIL** |

## Contract matrix

| # | Contract | Layer | Scenario | Primary test |
|---|----------|-------|----------|--------------|
| AB348a | `model_params_from_mapping` omits `temperature` / `top_p` when values are non-finite floats | unit | edge — `float("nan")`, `float("inf")` | `tests/tracing/test_genai_span_attrs.py::test_model_params_from_mapping_ignores_non_finite_float_fields[float_nan_inf]` |
| AB348b | String `"nan"` / `"inf"` for float knobs are rejected (mirror `_optional_int`) | unit | edge — malformed JSON strings | `test_model_params_from_mapping_ignores_non_finite_float_fields[string_nan_inf]` |

## W4 notes

- **#348 RED:** `_optional_float` (`tracing/genai.py:88`) returns `float(value)` without `math.isfinite`. `_optional_int` already rejects non-finite floats at line 77.
- **Existing green coverage:** `test_model_params_from_mapping_ignores_non_finite_int_fields` pins int knobs (`max_tokens`, `seed`) — unchanged.
- **D15:** W5 adds `math.isfinite` to `_optional_float` (and rejects string `"nan"` / `"inf"` via the same path).

## Acceptance (W4)

- New tests collect with zero import errors
- `make lint` + `make typecheck` clean on touched paths
- Both parametrized cases **XFAIL** (RED until W5)
- No `src/` edits; no D6 paths
