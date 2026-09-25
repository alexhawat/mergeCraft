# CI intelligence — test plan (K0 RED)

Wave plan: `.ignorelocal/waves/mergecraft-ci-intelligence-wave-plan.md`
Worktree: `mergecraft-ci-intelligence` @ `wave/ci-intelligence`

## xfail schedule

| Wave | Test files | Marker reason prefix |
|------|------------|----------------------|
| **K1** | `tests/ci/test_pipeline.py`, `tests/ci/test_redaction.py` (normalize half) | `green after K1:` |
| **K2** | `tests/ci/test_cluster.py`, `tests/ci/test_flaky.py`, `tests/ci/test_blame.py`, `tests/ci/test_redaction.py` (review half) | `green after K2:` |
| **K3** | `tests/ci/test_review_integration.py`, `tests/ci/test_redaction.py` (comment body) | `green after K3:` |

All cross-wave markers use `strict=False`. `tests/mcp/test_check_suite.py` is **not** xfailing — it guards the existing tool contract (K0.8 / K2).

## Normalized failure field table (K1.4)

| Field | Type / constraint | Test coverage |
|-------|-------------------|---------------|
| `job` | str — workflow job name | `test_pipeline.py`, fixtures |
| `step` | str — failing step name | `test_pipeline.py` |
| `command` | str — reproduced command | `test_pipeline.py`, `test_cluster.py` |
| `exit_code` | int — non-zero on failure | `test_pipeline.py` |
| `log_excerpt` | str — redacted excerpt | `test_pipeline.py`, `test_redaction.py` |
| `artifacts` | list[str] — redacted paths | `test_redaction.py` |
| `retry_state` | str \| null — attempt label | `test_flaky.py`, `flaky_retry_pass.json` |
| `failure_fingerprint` | str — stable hash | `test_pipeline.py`, `test_cluster.py` |

## Fingerprint definition (K1.4)

Stable hash derived from **normalized command + error signature** after redaction. Must **not** incorporate run ids, timestamps, or log line numbers. Asserted in:

- `test_pipeline.py::test_same_failure_signature_yields_identical_fingerprint`
- `test_pipeline.py::test_fingerprint_stable_across_run_ids`

## Flaky / blame decision matrix

Target matrix (authored RED in the CI-blame plan, then greened by its
`ci/paths.py` / `ci/flaky.py` / `ci/blame.py` waves):

| Condition | Expected classification | Blame on author? | Primary tests |
|-----------|-------------------------|------------------|---------------|
| Same fingerprint, attempt 1 fail → attempt 2 pass | `flaky` | No | `test_flaky.py`, `flaky_retry_pass.json` |
| Matching base run concluded `failure` | `pre_existing` (summary names the ref and `failed`) | No | `test_flaky.py`, `pre_existing_unrelated_failure.json` |
| Base run concluded `success` (or unrecognised) + failing attempts | `stable` (summary names the ref and `passed`) | Yes | `test_flaky.py` |
| Mixed base outcomes with ≥1 `failure` | `pre_existing`, naming the failing run's ref | No | `test_flaky.py` |
| Failure path in PR diff (normalised both sides) | `caused_by_pr` | Yes (subject to verifier) | `test_blame.py`, `blame_maps_to_diff_hunk.json` |
| No overlap, matching base run concluded `failure` | `probably_not_this_pr` | No | `test_blame.py`, `blame_unrelated_to_pr.json` |
| No overlap, base `success` / `cancelled` / absent | `unknown` (recorded `introduced_by_pr: "unknown"`, `Major`, blocks) | No — but blocking | `test_blame.py` |
| No path extracted at all, no base `failure` | `unknown`, `hunk is None`, no `ci/pipeline` sentinel | No — but blocking | `test_blame.py` |
| Two or more clusters + one scalar base status | scalar ignored; per-fingerprint `base_branch_runs` decide | — | `test_ci_intelligence.py` |

`caused_by_pr` still requires path overlap, and a passing base branch never promotes a
failure to it. Only a same-fingerprint base **failure** exonerates (compared after
`.strip().lower()`). Extraction reads failure context only — root files, `(line,col)`
and `./` forms included — so a `PASSED` line, a collection line, a command echo or a
bare URL is never a failure location. The `unknown` row is the honest third outcome:
it is recorded `"unknown"` (never `"false"`) and keeps the blocker.

## Recorded fixtures (K0.1)

| Fixture | Source | Scenario |
|---------|--------|----------|
| `multi_job_single_root_cause.json` | mergeCraft run `30450773730` | 12 shards, one provisioning failure |
| `flaky_retry_pass.json` | mergeCraft runs `30450773730` → `30452077517` | Same fingerprint fail then pass |
| `pre_existing_unrelated_failure.json` | sevn run `30367621815` | Drift gate fails; PR touches CI yaml only |
| `truncation_overflow.json` | mergeCraft + sevn failures | 5 failed runs; cap = 3 |
| `canary_in_ci_log.json` | synthetic echo on real excerpt | K8 redaction probe |
| `blame_maps_to_diff_hunk.json` | mergeCraft test failure | Diff touches failing test module |
| `blame_unrelated_to_pr.json` | sevn drift failure | Diff does not touch failing paths |

Raw capture zips live under `tests/ci/fixtures/raw/` (local-only; redacted JSON is committed).

## Contract matrix

| Decision | Unit | Integration | Functional | Primary tests |
|----------|------|-------------|------------|---------------|
| **K1** PipelineProvider | protocol + skip reason | stub vs GitHub | — | `test_pipeline.py` |
| **K1** normalization | field shape | fixture round-trip | — | `test_pipeline.py` |
| **K2** clustering | fingerprint key | 12 → 1 finding | — | `test_cluster.py` |
| **K4** flaky | retry flip | base branch evidence | — | `test_flaky.py` |
| **K3** blame | path overlap | base status | — | `test_blame.py` |
| **K5** truncation | cap constant | overflow message | review section | `test_review_integration.py` |
| **K6** cross-source cluster | — | CI + Ruff same line | — | `test_review_integration.py` |
| **K8** redaction | canary absent | ingest path | comment body | `test_redaction.py` |
| **K2** tool contract | `_analyze_log` | mocked MCP tool | — | `test_check_suite.py` |
| **D14** budget | inline cap | CI section placement | — | `test_review_integration.py` |

## Constants

- **Truncation default:** `3` (= current `failed[:3]` in `get_check_suite_logs`)
- **Inline budget:** `8` (D14 / W0.2)
- **CI section heading:** `### 🚨 CI failures`
- **Canary:** `tests/ci/support.py::CANARY_SECRET`
