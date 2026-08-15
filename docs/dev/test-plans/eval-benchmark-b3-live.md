# Eval benchmark B3 — live finding-location join test plan (RED)

Wave plan: `.ignorelocal/waves/issues-eval-benchmark-numbers-wave-plan.md` — PR B3 ("the centre of
the plan", N5)
Worktree: `mergecraft-bench-b3-live` @ `wave/bench-b3-live` (parent: `wave/bench-b2-gate`)
Anchors: `src/mergecraft/evals/benchmark.py` (`BenchmarkResultSet`, `run_structural_replay`,
`DEFAULT_BENCHMARK_PROVIDERS`) · `src/mergecraft/evals/scoring.py` (`score_findings`,
`fold_score_reports`, `ScoreReport`, `AggregateScoreReport`, `load_baseline_issues`,
`load_reported_findings`) · `src/mergecraft/cli/diff_review_cmd.py` (`--json`) ·
`src/mergecraft/harbor/agent.py` (`_PATCH_CANDIDATES`, read-only reference) ·
`src/mergecraft/utils/agent_resolve.py` (`has_credentials_for_slug`).

B3 has **no test-creator precedent** for its target shape — unlike B1/B2, none of the symbols this
plan pins exist yet (`evals/live_run.py` is a wholly new module). Everything below is this pass's
design proposal for the B3.2 implementer to confirm or override, exactly as B2.0's design gate did
for the crashed-run/neutral-decision subtlety, but for a brand-new module instead of a field
addition.

## Why this needs a design pass before tests, not just tests

`run_structural_replay()` (B1/B2, unchanged here) is pure, keyless, and free — it never touches a
live provider. B3 is the first thing in this plan that runs `mergecraft diff-review` for real,
which needs an LLM. That collides head-on with "RED tests must be local, keyless, deterministic."
The resolution below is a **dependency-injection seam**: the pure join (case → findings → score →
metrics) is one function that takes a findings-producing callable as a parameter; the RED suite
drives that function with a stub callable and never invokes an agent. The seam is also exactly what
`mergecraft eval bench` will wire a real subprocess call into in B3.2 — the tests pin the seam's
shape, not its production implementation.

## Design-gate findings (B3.0) — for the B3.2 implementer to confirm

### 1. Patch filename reuse — read, not imported

`harbor/agent.py:23` reads `_PATCH_CANDIDATES = ("task.patch", "changes.patch", "diff.patch",
"review.patch")`. `evals/live_run.py` reuses this **value**, duplicated as its own
`PATCH_CANDIDATES` constant — **not** imported from `mergecraft.harbor.agent`. Two reasons:

- `harbor` is an optional extra (`pyproject.toml:39`, `harbor==0.20.0`) — **not installed in this
  checkout** (`uv run python -c "import harbor"` → `ModuleNotFoundError`, verified live). Importing
  `mergecraft.harbor.agent` at module level pulls in `harbor.agents.installed.base`, which does not
  exist without the extra. B3.0's own bullet 4 says the in-repo corpus should not need Harbor at
  all — a hard import dependency on the `harbor` extra would silently reintroduce that coupling.
- The design gate says "reuse a patch filename … do not extend the tuple," which is a value
  constraint, not an import-path constraint.

**Locked here:** `mergecraft.evals.live_run.PATCH_CANDIDATES == ("task.patch", "changes.patch",
"diff.patch", "review.patch")`, verbatim, defined independently of `mergecraft.harbor.agent`. Tests
pin the tuple's value directly (hardcoded, commented with the line reference) rather than importing
`mergecraft.harbor.agent`, so the suite collects cleanly whether or not the `harbor` extra is
installed.

### 2. Missing-credential path — typed, not zero-filled

`evals/README.md`'s existing promise (`"With missing API keys the harness records skipped: no live
credential and omits those metrics"`) becomes two fields on `BenchmarkResultSet`:

```python
detection: DetectionMetrics | None = None
skipped_reason: str | None = None
```

Both default to `None` so an old committed result set (pre-B3, no `detection` key at all) still
validates under `extra="forbid"` (D3) — Pydantic fills the default rather than rejecting the
missing key. `detection` populated implies `skipped_reason is None`, and vice versa; that invariant
is exercised through the individual test scenarios below (never both set, never both `None` after a
real run attempt) rather than a `model_validator` this pass adds unprompted — see "not tested"
below for why a cross-field validator is left to B3.2's judgment.

### 3. Two distinct skip reasons, not one

The plan calls out **two** situations that must produce `detection=None` for entirely different
reasons, and the wave-generator prompt is explicit that conflating them is a mistake:

- **No live credential** — `evals/README.md`'s documented case. A detection corpus exists, but
  `has_credentials_for_slug(model)` (`utils/agent_resolve.py:99`, already used elsewhere in the
  codebase — reused here rather than reinvented) is `False` for the requested model.
- **No cases to detect on** — the corpus reality *today*: `evals/bench/mergecraft/` does not exist
  yet (B4's job). Even with a valid credential, there is nothing to run `diff-review` against.

**Locked here:**

```python
SKIP_REASON_NO_CREDENTIAL: Final[str] = "no live credential"
SKIP_REASON_NO_CASES: Final[str] = "no patch-bearing cases"
```

**Locked precedence:** case discovery is checked *before* the credential check. An empty corpus
short-circuits to `SKIP_REASON_NO_CASES` even when credentials are present — there is nothing
credential-gated to report. `test_run_detection_reports_no_cases_even_with_valid_credentials` pins
this ordering explicitly (credentials mocked present, corpus empty) so the two skip paths cannot be
silently conflated regardless of which the implementer's real environment happens to hit first.

**Implementation-assumption the tests monkeypatch against:** `evals/live_run.py` must import
`has_credentials_for_slug` by name into its own module namespace (`from
mergecraft.utils.agent_resolve import has_credentials_for_slug`), so the credential tests
monkeypatch `mergecraft.evals.live_run.has_credentials_for_slug` rather than the origin module. If
B3.2 instead calls it as `agent_resolve.has_credentials_for_slug(...)` via a module-qualified
import, these three tests need their monkeypatch target updated to match — that is a mechanical
fixup, not a contract change, and should be done by editing this test file's patch target only
(still test-creator territory per the escalation-receiver rule, since it is the test that would be
"wrong" — pinned to an implementation detail the plan does not actually require).

### 4. Local `diff-review` loop, never Harbor (confirmed, matches B3.0 bullet 4)

`cli/diff_review_cmd.py`'s `--json` flag (`diff_review_cmd.py:57-60`) writes structured findings to
a file via `run_offline_diff_review(..., json_path=...)` →
`analyzers/finding.py:write_findings_json` → `json.dumps({"findings": [Finding.model_dump(), ...]})`
(`finding.py:168-172`, confirmed by reading the source). That envelope shape (`{"findings": [...]}`)
is **already** one of the three keys `scoring.py`'s `_rows()` recognizes
(`scoring.py:327`), so `load_reported_findings()` consumes a `diff-review --json` output file with
zero adaptation. This is the concrete evidence that "drive the corpus locally" means: for each
patch-bearing case, materialize its patch into a working tree, run
`mergecraft diff-review --cwd <worktree> --diff <patch> --json <path>` as a subprocess (or via
`run_offline_diff_review` directly — implementer's call), then feed the written JSON straight into
`load_reported_findings()`. A live LLM call happens inside that subprocess and needs a real key —
which is exactly the seam `review_fn` isolates from the RED suite (see the "Why this needs a design
pass" section above).

## The `evals/live_run.py` contract this test file pins

None of these symbols exist yet — every test that imports them fails today via `ImportError`
(module does not exist) at collection time, which is the expected and correct RED signature for
this PR specifically (unlike B1/B2, where every referenced symbol already existed and RED came from
`AttributeError`/`ValidationError` at call time).

```python
PATCH_CANDIDATES: Final[tuple[str, ...]]          # see finding 1
BASELINE_FILENAME: Final[str] = "baseline.json"
DEFAULT_DETECTION_CORPUS_DIR: Final[Path] = Path("evals/bench/mergecraft")
SKIP_REASON_NO_CREDENTIAL: Final[str] = "no live credential"
SKIP_REASON_NO_CASES: Final[str] = "no patch-bearing cases"

class DetectionCase(BaseModel):        # extra="forbid"
    case_id: str
    patch_path: Path
    baseline_path: Path
    closed_world: bool = False

class DetectionCaseResult(BaseModel):  # extra="forbid" — per-case row, mirrors
                                        # CaseReplayRow's role in BenchmarkMetrics
    case_id: str
    closed_world: bool
    total_issues: int
    total_reported: int
    found: int
    recall: float
    corpus_confirmed_precision: float
    f1: float
    strict_precision: float | None = None   # None on an open-world case (D4:
                                             # ScoreReport.strict_precision raises there)

class DetectionMetrics(BaseModel):     # extra="forbid"
    provider: str
    model: str
    cases_run: int
    aggregate: AggregateScoreReport
    case_results: list[DetectionCaseResult]
    raw_findings_dir: str

ReviewFn = Callable[[DetectionCase], list[dict[str, Any]]]

def discover_detection_cases(
    corpus_dir: Path = DEFAULT_DETECTION_CORPUS_DIR,
) -> list[DetectionCase]: ...

def run_live_detection(
    cases: list[DetectionCase],
    *,
    provider: str,
    model: str,
    review_fn: ReviewFn,
    results_dir: Path,
    slack: int = DEFAULT_LINE_SLACK,
) -> DetectionMetrics: ...

def run_detection(
    *,
    provider: str,
    model: str,
    corpus_dir: Path = DEFAULT_DETECTION_CORPUS_DIR,
    results_dir: Path,
    review_fn: ReviewFn | None = None,
) -> tuple[DetectionMetrics | None, str | None]:
    """Returns (metrics, None) on a real run, or (None, skip_reason) per findings 2/3."""

def run_full_benchmark(
    bank_dir: Path = DEFAULT_BANK_DIR,
    *,
    detection_corpus_dir: Path = DEFAULT_DETECTION_CORPUS_DIR,
    results_dir: Path = DEFAULT_RESULTS_DIR,
    providers: tuple[str, ...] = DEFAULT_BENCHMARK_PROVIDERS,
    detection_provider: str = "claude",
    detection_model: str = "claude-sonnet-5",
    review_fn: ReviewFn | None = None,
) -> BenchmarkResultSet:
    """Joins run_structural_replay() (benchmark.py, unchanged) with run_detection()
    into one result set carrying both sections."""
```

**Corpus-on-disk format this pass invents (B4 must follow it):** each case is a directory under
`evals/bench/mergecraft/<case_id>/` containing one file named from `PATCH_CANDIDATES` (the patch)
and a `baseline.json` shaped `{"closed_world": bool, "issues": [<BaselineIssue-compatible rows>]}`.
The `"issues"` envelope key is one `load_baseline_issues()` already accepts (`scoring.py:327`), so
no new parsing logic is needed on the scoring side. **This is a test-creator judgment call, not
something the plan states explicitly** — B3.2 and B4 should treat it as the working default and
override here (updating this doc) if a different on-disk shape proves better once real cases exist.

**Not tested here (explicitly deferred to B3.2's judgment):**

- A `model_validator` enforcing "`detection` and `skipped_reason` are never both set / both unset
  after a real orchestration call" — the individual scenario tests below already pin the correct
  value pair for each path (populated-detection, no-credential, no-cases), which is the behaviour
  that actually matters; adding a schema-level invariant is a reasonable hardening B3.2 may choose
  to add, but is not required to pass this suite.
- The production (non-injected) default for `review_fn` — i.e., the actual subprocess/CLI
  invocation of `mergecraft diff-review`. Finding 4 above pins what that path must produce
  (`{"findings": [...]}` JSON compatible with `load_reported_findings()`), but exercising it for
  real needs a live LLM call, which is out of scope for a keyless RED suite. No `MERGECRAFT_LIVE_E2E`
  gate is added in this pass — B3.2 or a later wave can add one if a true integration test is
  wanted.
- `mergecraft eval bench` CLI wiring and `make bench-detect` / `make reference-docs` (D14) — B3.2's
  job per the plan; this pass only pins the pure orchestration layer `live_run.py` exposes.

## Locked decisions exercised

| ID | Decision | Tests |
|----|----------|-------|
| **D3** | `BenchmarkResultSet` extended, never replaced; `extra="forbid"` preserved; an old result set without `detection`/`skipped_reason` still validates | `test_benchmark_result_set_without_a_detection_section_still_parses`, `test_full_benchmark_structural_section_matches_a_bare_structural_replay` |
| **D4** | `strict_precision` is closed-world-only; `None` (not a raise) on `DetectionCaseResult` for an open-world case | `test_end_to_end_fixture_corpus_produces_correct_prf1`, `test_detection_case_result_omits_strict_precision_for_open_world_case` |
| **D7** | Two corpora, two questions — bank cases (no patch) never surface as detection cases | `test_discover_detection_cases_ignores_a_directory_without_baseline_or_patch` |
| B3.0 finding 1 | Reuse `_PATCH_CANDIDATES` verbatim, do not extend, do not hard-import `harbor` | `test_patch_candidates_matches_harbor_agent_verbatim` |
| B3.0 finding 2/3 | Typed skip states, two distinct reasons, correct precedence | `test_run_detection_reports_no_credential`, `test_run_detection_reports_no_cases_even_with_valid_credentials`, `test_run_detection_prefers_no_cases_over_no_credential_when_both_are_true` |
| evals/README.md promise | `skipped: no live credential`, metrics omitted never fabricated | `test_run_detection_reports_no_credential`, `test_full_benchmark_omits_detection_when_no_credential` |

## xfail schedule

None. Every test in `tests/evals/test_live_run.py` fails today via **collection-time `ImportError`**
(`evals/live_run.py` does not exist) — the correct and expected RED signature for this PR, per the
dispatch prompt's explicit note that this differs from B1/B2. No `xfail` markers are used because
there is nothing meaningful to mark `xfail` against a module that does not exist yet; a bare
`ImportError` already fails the whole file, which is the intended all-or-nothing RED for B3.

## Contract matrix

| Contract | Layer | Scenario | Primary test |
|----------|-------|----------|--------------|
| Fixture corpus (1 open-world + 1 closed-world case) → detection section populated, P/R/F1 hand-computed | Functional/E2E | Happy | `test_end_to_end_fixture_corpus_produces_correct_prf1` |
| Zero findings on a clean (closed-world) case → `strict_precision == 1.0` in the detection section | Integration | Edge | `test_end_to_end_fixture_corpus_produces_correct_prf1` (asserts on the clean case's `DetectionCaseResult`) |
| Open-world case's `DetectionCaseResult.strict_precision` is `None`, not a raise | Unit | Edge | `test_detection_case_result_omits_strict_precision_for_open_world_case` |
| No credentials → `detection is None`, `skipped_reason == "no live credential"`, `review_fn` never invoked | Integration | Error | `test_run_detection_reports_no_credential` |
| No patch-bearing cases → `detection is None`, `skipped_reason == "no patch-bearing cases"`, even with valid credentials | Integration | Error | `test_run_detection_reports_no_cases_even_with_valid_credentials` |
| Precedence: empty corpus wins over missing credential | Integration | Edge | `test_run_detection_prefers_no_cases_over_no_credential_when_both_are_true` |
| `discover_detection_cases` skips a bank-style directory with no patch/no baseline (D7) | Unit | Edge | `test_discover_detection_cases_ignores_a_directory_without_baseline_or_patch` |
| `discover_detection_cases` on a missing corpus dir returns `[]`, not an error | Unit | Edge | `test_discover_detection_cases_on_a_missing_dir_returns_empty` |
| `PATCH_CANDIDATES` matches `harbor/agent.py` verbatim, not extended | Unit | Happy (regression) | `test_patch_candidates_matches_harbor_agent_verbatim` |
| `run_full_benchmark` joins structural + detection; structural section is bit-identical to a bare `run_structural_replay()` call | Integration | Happy | `test_full_benchmark_structural_section_matches_a_bare_structural_replay` |
| `run_full_benchmark` with no credentials still populates the structural section (join must not break B1/B2) | Integration | Error | `test_full_benchmark_omits_detection_when_no_credential` |
| `BenchmarkResultSet` without a `detection` key still parses (D3 forward-compat) | Unit | Happy (regression) | `test_benchmark_result_set_without_a_detection_section_still_parses` |
| Raw findings persisted under `raw_findings_dir` per case | Integration | Happy | `test_end_to_end_fixture_corpus_produces_correct_prf1` (asserts the written file exists) |

## Verification

- `MERGECRAFT_PYTEST_JOBS=0 uv run pytest tests/evals/test_live_run.py -q` — collects and fails via
  `ImportError: No module named 'mergecraft.evals.live_run'` at collection time (confirmed: this is
  the only new-module import in the file; every other imported symbol — `AggregateScoreReport`,
  `BenchmarkResultSet`, `run_structural_replay`, `has_credentials_for_slug`, `add_case`, `Case` —
  already exists and resolves cleanly).
- `MERGECRAFT_PYTEST_JOBS=0 uv run pytest tests/evals --collect-only -q` — confirms the new file's
  collection failure is isolated to itself and does not break collection of the rest of
  `tests/evals/`.
- `make lint` — clean.
- `make typecheck` — mypy strict is scoped to `src/mergecraft` only (`Makefile:67`); this test file
  is not mypy-checked, consistent with B1/B2's note.
