# PR AP4 — change classifier and lens routing — test plan (AP4.1)

Wave plan: `.ignorelocal/03-agent-pipeline-wave-plan.md` (PR AP4)
Worktree: `../mergecraft-agent-pipeline` @ `feature/agent-pipeline-ap4`
Authoring wave: **AP4.1** (tests-first). Implementation: **AP4.2**.
xfail-reconciliation: **post-AP4.2** (pending).

Locked decisions: **D2** (registry selects 3–8 per run in typical cases; only routed
agents render — routing must not invent ids outside the registry), **convention 6**
(no fixed specialist cap — every matching lens may be selected).

## xfail schedule

All ten AP4.1 tests use `@pytest.mark.xfail(reason="AP4.2", strict=True)` until
AP4.2 lands. Post-AP4.2 reconciliation removes the markers.

| Test file | Tests | Marker | Status at AP4.1 |
|-----------|-------|--------|-----------------|
| `tests/classify/test_change_classifier.py` | 4 | `AP4.2` | **RED (xfail)** |
| `tests/review/test_lens_routing.py` | 6 | `AP4.2` | **RED (xfail)** |

**Acceptance (AP4.1):** 10 collected; 0 pass; 10 xfail. `make lint` + `make typecheck`
clean.

## Target API AP4.2 must satisfy

### `src/mergecraft/classify/change_classifier.py` (new)

| Symbol | Contract |
|--------|----------|
| `ChangeClassification` | Pydantic: `risk_band` (`low`/`medium`/`high`), `blast_radius` (`BlastRadiusClassification`), `change_map` (typed dict with `changed_paths`, `categories`, `generated_paths`, `vendored_paths`), `is_trivial` (`bool`) |
| `classify_change(change, *, rule_set=None, agent_runner=None)` | Builds typed change/risk map; **`risk_band` must match `classify_blast_radius(change).lane`**; surfaces generated/vendored paths; invokes `agent_runner` **exactly once** when supplied |

Reuses `mergecraft.classify.blast_radius.classify_blast_radius` — no parallel
risk rule set.

### `src/mergecraft/review/lens_routing.py` (new)

| Symbol | Contract |
|--------|----------|
| `LensRoutingEntry` | `lens_id`, `selected` (`bool`), `reason` (`str`, non-empty) |
| `LensRoutingDecision` | `selected_lens_ids` (`tuple[str, ...]`), `entries` (`tuple[LensRoutingEntry, ...]`) covering **every** registry lens |
| `load_routing_registry(settings, repo_root)` | Loads core roles plus lens bindings with declarative trigger metadata (`categories`, `minRiskBand`, …) for AP5 expansion |
| `Registry.iter_lens_bindings()` | Yields lens `AgentBinding` rows (AP4.2 extends registry) |
| `route_lenses(classification, *, registry)` | Intersects classifier output with each lens's trigger signals; records why each lens ran or was skipped; **no fixed cap** on selected count |

`modes/Review.py` step 4 must consume `route_lenses` (wired in AP4.2).

Triviality follows the Review prompt contract: doc typo → trivial / zero lenses;
one-line billing/auth/SQL change → **not** trivial despite small diff stats.

## Contract → coverage matrix

### `tests/classify/test_change_classifier.py` — 4 tests

| # | Test | Layer | Scenario | Contract |
|---|------|-------|----------|----------|
| 1 | `test_emits_typed_risk_and_change_map` | unit | happy | Typed `ChangeClassification` with aligned `risk_band` / `change_map` |
| 2 | `test_detects_generated_and_vendored_files` | unit | edge | `generated_paths` and `vendored_paths` populated explicitly |
| 3 | `test_risk_band_reflects_blast_radius` | integration | reuse | `risk_band` and `blast_radius` match `classify_blast_radius` output |
| 4 | `test_classifier_makes_one_cheap_call` | unit | cost guard | `agent_runner` invoked exactly once |

### `tests/review/test_lens_routing.py` — 6 tests

| # | Test | Layer | Scenario | Contract |
|---|------|-------|----------|----------|
| 5 | `test_routing_selects_from_the_registry` | integration | happy | Selected ids ⊆ registry lens ids |
| 6 | `test_trivial_change_routes_zero_lenses` | functional | trivial skip | `is_trivial` doc typo → empty selection |
| 7 | `test_one_line_billing_change_is_not_trivial` | functional | guard-deletion | One-line billing change not trivial; routes ≥1 lens |
| 8 | `test_migration_diff_routes_the_migration_lens` | integration | happy | Migration diff selects `schema-migration` |
| 9 | `test_no_fixed_cap_on_lens_count` | integration | convention 6 | Multi-signal diff selects ≥9 lenses (no fixed cap) |
| 10 | `test_routing_decision_is_recorded_with_its_reason` | integration | observability | Every lens has `selected` + non-empty `reason`; skipped lenses recorded |

## Imports of not-yet-existing symbols

`mergecraft.classify.change_classifier` and `mergecraft.review.lens_routing`
symbols are imported **inside test bodies** (or helpers those bodies call) so
collection succeeds before AP4.2.

## Status

AP4.1 RED suite authored; AP4.2 implementation pending; xfail markers remain
until post-AP4.2 reconciliation.
