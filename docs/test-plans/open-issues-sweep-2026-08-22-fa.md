# Open issues sweep 2026-08-22 — Batch FA test plan (#394)

Wave plan: `.ignorelocal/waves/open-issues-sweep-2026-08-22-wave-plan.md`
Worktree: `.ignorelocal/worktrees/repo-state-2026-08-22-sweep` @ `wave/repo-state-2026-08-22-sweep`
Authoring wave: **W1** (FA RED) · Implementation: **W2** (`provider_health.py` critical routing)

## xfail schedule

| Wave | Test | Marker reason | Status |
|------|------|---------------|--------|
| **W2** | `test_route_model_per_specialist_and_risk` | `green after W2: critical-risk security routing (#394)` | reconciled @ `72b80ece` — marker removed |

## Contract matrix

| # | Contract | Layer | Scenario | Primary test |
|---|----------|-------|----------|--------------|
| FA394a | `route_model(security, high)` stays on capable pick (`anthropic/claude-opus`) | unit | happy (regression) | `tests/agents/test_ce_providers.py::test_route_model_per_specialist_and_risk` |
| FA394b | `route_model(security, critical)` is **not** `anthropic/claude-haiku` | unit | happy | same |
| FA394c | `route_model(security, critical)` equals `route_model(security, high)` (D7) | unit | happy | same |
| FA394d | `medium` / `low` / `trivial` security bands stay on cheap pick unless `_ROUTE_TABLE` has a row | unit | edge | same (`trivial` has explicit Haiku row; `medium`/`low` use fallback) |

## W1 RED evidence (@ `243eaf01`)

- `route_model(specialist="security", risk="critical")` → `anthropic/claude-haiku` (bug: falls through `else` branch).
- `route_model(specialist="security", risk="high")` → `anthropic/claude-opus` (baseline for D7).
- `route_model(specialist="security", risk="medium"|"low"|"trivial")` → `anthropic/claude-haiku` (passes today; regression guard for W2).

## Out of scope

- `cli/profiles.py` `_RISK_TO_PROFILE` (read-only alignment reference).
- Provider drivers, `agents/registry.py`, `agents/verifier.py` (D6).
