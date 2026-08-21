# Open issues sweep 2026-08-20d-b-runtime — test plan

Wave plan: `.ignorelocal/waves/open-issues-sweep-2026-08-20d-b-runtime-wave-plan.md`
Worktree: `../mergecraft-20d-b-runtime` @ `wave/20d-b-runtime`
Authoring waves: **W7.1** (#381), **W8.1** (#382), **W10.1** (#384)

Implementation waves (do not edit these tests): W7.2, W8.2, W10.2.
Recon after each impl wave removes the matching non-strict `xfail` markers.

**W7.2 recon (2026-08-21, `99847292`):** all `tests/enterprise/` `green after W7.2` markers
removed after 45/45 XPASS on `c32b2eae`. W8.2 (`tests/release/`) and W10.2
(`tests/evals/`) xfails left in place. No assertion edits; no leftover
enterprise xfail. `tests/enterprise/`: 46 passed, 0 fail, 0 xfail.

**W8.2 recon (2026-08-21, `80b6b728`):** all `tests/release/` `green after W8.2`
markers removed after 12/12 XPASS on `2376589e`. W7.2 enterprise markers
already gone; W10.2 (`tests/evals/`) xfails left in place. No assertion
edits; no leftover release xfail. `tests/release/`: 15 passed, 0 fail,
0 xfail. DCF.1 may run on this branch.

D17: new CLI tests live under `tests/enterprise/`, not `tests/cli/`. No
`mergecraft.cli.app` imports. D10: `test_no_eval_scores_on_landing_readme`
stays green; this suite mirrors it and never asserts scores belong on README.
D14: runtime only — no standalone binary. D19: support matrix is generated.

## xfail schedule

All cross-wave markers use `@pytest.mark.xfail(..., strict=False)`.

| Wave | Test module | Marker reason | Status |
| --- | --- | --- | --- |
| **W7.2** | `tests/enterprise/test_proxy.py` | `green after W7.2: enterprise proxy (#381)` | GREEN — markers removed |
| **W7.2** | `tests/enterprise/test_certificates.py` | `green after W7.2: custom CA path (#381)` | GREEN — markers removed |
| **W7.2** | `tests/enterprise/test_offline_install.py` (xfails only) | `green after W7.2: offline install path (#381)` | GREEN — markers removed |
| **W7.2** | `tests/enterprise/test_telemetry.py` | `green after W7.2: telemetry opt-out contract (#381)` | GREEN — markers removed |
| **W7.2** | `tests/enterprise/test_residency.py` | `green after W7.2: data-residency controls (#381)` | GREEN — markers removed |
| **W7.2** | `tests/enterprise/test_health.py` | `green after W7.2: health endpoint (#381)` | GREEN — markers removed |
| **W7.2** | `tests/enterprise/test_audit.py` | `green after W7.2: audit and usage export (#381)` | GREEN — markers removed |
| **W7.2** | `tests/enterprise/test_support_bundle.py` | `green after W7.2: support bundle with redaction (#381)` | GREEN — markers removed |
| **W7.2** | `tests/enterprise/test_policy_memory_distribution.py` | `green after W7.2: org policy/memory without dashboard (#381)` | GREEN — markers removed |
| **W7.2** | `tests/enterprise/test_retention_diagnostics.py` | `green after W7.2: retention and operational diagnostics (#381)` | GREEN — markers removed |
| **W7.2** | `tests/enterprise/test_cli_verbs.py` | `green after W7.2: enterprise CLI verbs (#381)` | GREEN — markers removed |
| **W8.2** | `tests/release/test_support_matrix.py` (xfails only) | `green after W8.2: generated six-axis support matrix (#382)` | GREEN — markers removed |
| **W8.2** | `tests/release/test_rc_soak_docs.py` | `green after W8.2: RC/soak process doc (#382)` | GREEN — markers removed |
| **W8.2** | `tests/release/test_security_response.py` (xfails only) | `green after W8.2: security-response / vulnerability-disclosure (#382)` | GREEN — markers removed |
| **W10.2** | `tests/evals/test_quality_metric_set.py` | `green after W10.2: eval quality metric set (#384)` | RED @ W10.1 |
| **W10.2** | `tests/evals/test_ablation_harness.py` | `green after W10.2: eval ablation harness (#384)` | RED @ W10.1 |
| **W10.2** | `tests/evals/test_golden_corpus_expansion.py` | `green after W10.2: eval corpora expansion (#384)` | RED @ W10.1 |
| **W10.2** | `tests/evals/test_eval_methodology_docs.py` (xfails only) | `green after W10.2: published eval methodology page (#384)` | RED @ W10.1 |

GREEN (no xfail) — must stay passing through impl:

| Pin | Test |
| --- | --- |
| D10 README scores | `tests/docs/test_docs_gate.py::test_no_eval_scores_on_landing_readme` **and** `tests/evals/test_eval_methodology_docs.py::test_no_eval_scores_on_landing_readme_d10` |
| D10 path | `test_eval_methodology_is_not_readme` |
| D19 RD1 generator | `test_gen_docs_still_dispatches_rd1_generators` |
| D19 compatibility-matrix | `test_compatibility_matrix_stays_ungenerated_contributor_notes` |
| #343 ADR | `test_python_version_floor_adr_exists` |
| Existing SECURITY.md reporting | `test_security_md_already_points_at_private_advisories` |

## Intended public API (W7.2)

| Module | Symbols |
| --- | --- |
| `src/mergecraft/enterprise/proxy.py` | `ProxyConfig`, `apply_enterprise_proxy` |
| `src/mergecraft/enterprise/certificates.py` | `CustomCAError`, `load_custom_ca` |
| `src/mergecraft/enterprise/offline.py` | `offline_install_plan`, `OfflineInstallError` |
| `src/mergecraft/enterprise/telemetry.py` | `TelemetryMode`, `resolve_telemetry_mode`, `is_telemetry_export_enabled` |
| `src/mergecraft/enterprise/residency.py` | `DataResidencyPolicy`, `enforce_data_residency` |
| `src/mergecraft/enterprise/health.py` | `HEALTHZ_PATH` (`/healthz`), `health_payload`, `build_health_app` |
| `src/mergecraft/enterprise/audit.py` | `export_audit_log`, `export_usage`, `explain_blocking_decision` |
| `src/mergecraft/enterprise/support_bundle.py` | `write_support_bundle` |
| `src/mergecraft/enterprise/policy_distribution.py` | `distribute_org_policy` (wraps `mergecraft.policy`) |
| `src/mergecraft/enterprise/memory_distribution.py` | `bind_org_memory` (wraps `mergecraft.memory.OrganizationMemoryBackend`) |
| `src/mergecraft/enterprise/retention.py` | `TraceRetentionPolicy`, `PrivacyLogMode` |
| `src/mergecraft/enterprise/diagnostics.py` | `operational_diagnostics` |
| `src/mergecraft/cli/health_cmd.py` | Typer `app` |
| `src/mergecraft/cli/audit_cmd.py` | Typer `app` with `export` |
| `src/mergecraft/cli/support_bundle_cmd.py` | Typer `app` with `--output` |

Lane A owns `cli/app.py`: one additive `app.add_typer` line per verb in W7.2, nothing else.

## Intended public API (W8.2)

| Surface | Contract |
| --- | --- |
| `docs/support-matrix.md` | Generated; six axes OS, SCM, languages, analyzers, providers, models |
| `docs/manifest.yaml` | Row `path: docs/support-matrix.md`, `generator: support-matrix` |
| `scripts/gen_docs.py` | Dispatch that generator; keep RD1 `gen_reference_docs` / index / llms-full |
| `docs/release-process.md` | RC, soak, changelog, migration notes; manifest row |
| `SECURITY.md` | Security-response heading + coordinated / vulnerability disclosure |

Do not hand-edit `docs/compatibility-matrix.md` into the six-axis matrix.

## Intended public API (W10.2)

| Module | Symbols |
| --- | --- |
| `src/mergecraft/evals/quality_metrics.py` | `QualityMetrics`, `compute_quality_metrics` |
| `src/mergecraft/evals/ablation.py` | `ABLATION_DIMENSIONS`, `AblationConfig`, `run_ablation` |
| `src/mergecraft/evals/corpora.py` | `GOLDEN_CATEGORIES`, `GOLDEN_CORPUS_DIR`, `MUTATION_CORPUS_DIR`, `BENCHMARK_CASE_KINDS`, `golden_languages`, `cases_for_kind` |
| `docs/eval-methodology.md` | Manifest row; methodology; no README scores; do not steal #140 |

## Contract matrix

### Batch DB — #381

| # | Contract | Layer | Scenario | Primary test |
| --- | --- | --- | --- | --- |
| DB381a | Enterprise proxy | unit | happy/edge/error | `test_apply_enterprise_proxy_sets_https_proxy`, `test_apply_enterprise_proxy_honours_no_proxy`, `test_invalid_proxy_url_raises` |
| DB381b | Custom CA | unit | happy/error | `test_load_custom_ca_returns_ssl_context`, `test_load_custom_ca_missing_file_raises`, `test_load_custom_ca_rejects_invalid_pem` |
| DB381c | Offline install | unit | happy/error | `test_offline_install_plan_uses_python_311_floor`, `test_offline_install_rejects_standalone_binary_request` |
| DB381d | Telemetry on/opt-out/off | unit | happy/edge/error | `tests/enterprise/test_telemetry.py` |
| DB381e | Data residency | unit | happy/edge/error | `tests/enterprise/test_residency.py` |
| DB381f | `/healthz` JSON | unit + integration | happy/error | `tests/enterprise/test_health.py` |
| DB381g | Audit + usage JSON | unit | happy/edge/error | `tests/enterprise/test_audit.py` |
| DB381h | Support bundle redaction | unit | happy/edge/error | `tests/enterprise/test_support_bundle.py` |
| DB381i | Policy/memory without dashboard | integration | happy/error | `tests/enterprise/test_policy_memory_distribution.py` |
| DB381j | Retention + diagnostics | unit | happy/error | `tests/enterprise/test_retention_diagnostics.py` |
| DB381k | CLI verbs as `*_cmd.py` | functional | happy | `tests/enterprise/test_cli_verbs.py` |

Out of scope honoured: no install-docs rewrite; no standalone binary; do not re-author `policy/**` / `memory/**`.

### Batch DC — #382

| # | Contract | Layer | Scenario | Primary test |
| --- | --- | --- | --- | --- |
| DC382a | Six-axis matrix generated + manifest | integration | happy | `test_support_matrix_registered_in_manifest_as_generated`, `test_generated_support_matrix_covers_six_axes` |
| DC382b | RD1 generator dispatch / docs-check | integration | happy | `test_gen_docs_dispatches_support_matrix_generator`, `test_docs_check_covers_support_matrix_via_gen_docs` |
| DC382c | Not a hand table | unit | edge | `test_support_matrix_header_marks_generated_not_hand_edited` |
| DC382d | compatibility-matrix unchanged role | unit | current GREEN | `test_compatibility_matrix_stays_ungenerated_contributor_notes` |
| DC382e | RC/soak process doc | functional | happy/error | `tests/release/test_rc_soak_docs.py` |
| DC382f | Security-response + disclosure | unit | happy | `tests/release/test_security_response.py` |

Out of scope honoured: docs system itself (RD1); config schema versioning.

### Batch DE — #384

| # | Contract | Layer | Scenario | Primary test |
| --- | --- | --- | --- | --- |
| DE384a | Metric set | unit | happy/edge/error | `tests/evals/test_quality_metric_set.py` |
| DE384b | Ablation harness | unit | happy/error | `tests/evals/test_ablation_harness.py` |
| DE384c | Golden vs mutation corpora | unit | happy/error | `tests/evals/test_golden_corpus_expansion.py` |
| DE384d | Methodology docs page | functional | happy/error | `tests/evals/test_eval_methodology_docs.py` |
| DE384e | No README scores (D10) | functional | GREEN | `test_no_eval_scores_on_landing_readme` / `_d10` |

Out of scope honoured: adversarial corpora; #219 / #220; never close #140.

## Acceptance (W7.1 / W8.1 / W10.1)

- Suite collects with zero import/collection errors
- `make lint` + `make typecheck` clean
- Cross-wave tests XFAIL (`strict=False`); GREEN pins PASS
- No `src/` edits; no `tests/cli/` rewrites; no README scores asserted
