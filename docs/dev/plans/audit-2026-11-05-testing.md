# Testing, CI and release audit — 2026-11-05

Audited source: `55cf88e33c318a8b03a251fb0f8b6dad9d999141` in the audit checkout. This memo uses current hosted results and current source, not September's coverage numbers. It excludes the open-work snapshot's proposed fixes, dependency advisory #1162, freshness issue #1169, and existing evaluation/labeling work. It distinguishes an observed functional defect from an assurance gap.

The test suite is substantial and materially better than the September baseline. Its unit, policy, security and configuration coverage is credible. It does not yet justify treating the application as an independently validated reviewer across all its advertised CLI, harness, platform and Action combinations. The main weaknesses are at boundaries: the installed package, real external CLI protocols, complete Action publication, and decision accuracy. Two test mechanisms still accept demonstrably bad outcomes. High coverage and passing structural evaluation should not be presented as evidence of high finding precision or recall.

## Current execution evidence

| Evidence | Commit and observed result | What it establishes |
|---|---|---|
| [CI, exact audited SHA](https://github.com/alexhawat/mergeCraft/actions/runs/42102257661) | Python 3.14 shard 1: **7,064 passed, 21 skipped, 1 xfailed**; shard 2: **7,074 passed, 12 skipped**. Python 3.11 shards, both static/build and security jobs also succeeded. | 14,138 passing parameterized unit cases in the two Python 3.14 shards. Skip totals cannot be treated as unique cases because module-level collection skips can repeat across shards. |
| [Coverage job, exact SHA](https://github.com/alexhawat/mergeCraft/actions/runs/42102257661/job/127508319743) | Artifact `13448484775`, `mergecraft-coverage-json`: **87.91% statements**, **77.58% branches**, **85.29% combined**. | Current source coverage, including the separate coverage-marked branch-walking cases. It does not measure real provider detection accuracy. |
| [Integration, exact SHA](https://github.com/alexhawat/mergeCraft/actions/runs/42102257705) | Python 3.14: **19 passed, 8 skipped**. Both supported Python endpoints succeeded. Separate privileged job passed **4 + 1 + 5** cases. | Real keyless provider-failure integration behavior; actual Linux privileged egress/ownership/UID assertions in a separate lane. The old file-existence sentinel is gone. |
| [Mutation, exact SHA](https://github.com/alexhawat/mergeCraft/actions/runs/42102257661/job/127508231486) | **108 sampled mutants; 43 survive (39.8%)**; passes aggregate 45% escape threshold. Advisory. | A weak-to-moderate sampled assertion-strength signal, subject to the infrastructure-error classification bug below. It is not a full mutation score for the repository. |
| [Nightly E2E](https://github.com/alexhawat/mergeCraft/actions/runs/42033340202/job/127265043074) | Earlier same-day SHA `2ed1214384477df51978490286801274e1e16167`: **168 in-image adversarial tests passed**. Installed OpenCode harness using `opencode-go/deepseek-v4.1-flash` returned `terminal_review: true`, `outcome: passed`. | Actual installed harness/provider/terminal protocol worked on one simple offline diff. It is useful evidence and stronger than canned output. This was not the audited SHA, a PR publication test, or a detection benchmark. |
| [Nightly Integration](https://github.com/alexhawat/mergeCraft/actions/runs/42036196191) | Same earlier `2ed1214` SHA: GitHub live lane passed; nightly randomized unit run **13,488 passed, 31 skipped, 1 xfailed**. | There is now a changing-seed run beyond the fixed PR seed. GitHub live integration works; this does not imply all model vendors are tested. |
| [CI/CD, exact SHA](https://github.com/alexhawat/mergeCraft/actions/runs/42102257537) | Still in progress at the final audit check on 2026-11-05. | Do not describe this particular source as successfully released solely because its unit CI passed. |
| [Published prerelease](https://github.com/alexhawat/mergeCraft/releases/tag/v0.1.0a4) | `v0.1.0a4`, published 2026-10-29; wheel, sdist and build metadata assets. | A published Python artifact exists. Release age and successful source CI alone do not establish runtime parity with today's main. |

The exact-SHA Docker run [42102257709](https://github.com/alexhawat/mergeCraft/actions/runs/42102257709) and CodeQL run [42102257516](https://github.com/alexhawat/mergeCraft/actions/runs/42102257516) also succeeded. No local full suite, build, install, live provider call or image download was performed for this audit. The parent audit additionally ran **122 selected existing synchronous tests** using the existing application runtime and a cached pytest package: 82 triage-recognizer tests and 40 triage-tier/adapter/impact/cluster tests. The async plugin was disabled, so that local result is not evidence about async tests. The broad measurements above come from GitHub; the two false-green probes below use only the standard library and in-memory substitutes.

## Quantitative spread

AST inventory of `tests/**/test_*.py`: **1,093 files**, **9,372 test function definitions**, **239,824 physical lines**. Parameterization explains why runtime case counts are higher. **8,904 definitions contain an explicit Python `assert`**. The remaining 468 are not automatically weak: exception assertions, delegated helpers and fixtures can legitimately carry the oracle. Conversely, the presence of `assert` says nothing about whether the expected answer is correct.

| Test directory | Files | Test definitions |
|---|---:|---:|
| cli | 109 | 1,018 |
| analyzers | 90 | 1,003 |
| agents | 89 | 802 |
| ci | 102 | 782 |
| mcp | 80 | 702 |
| utils | 47 | 517 |
| evals | 46 | 446 |
| review | 36 | 430 |
| tracing | 72 | 369 |
| evidence | 32 | 363 |
| config | 39 | 324 |
| security | 35 | 285 |
| classify | 11 | 260 |
| tests root | 18 | 186 |
| findings | 25 | 177 |
| policy | 16 | 166 |
| jev | 23 | 160 |
| docs | 22 | 148 |
| verify | 19 | 137 |
| review_record | 18 | 116 |
| scripts | 7 | 106 |
| enterprise | 16 | 84 |
| context | 13 | 74 |
| harness | 16 | 63 |
| release | 8 | 53 |
| xrepo | 7 | 45 |
| pins / review_policy | 5 / 5 | 42 / 42 |
| modes / scm | 8 / 7 | 41 / 41 |
| prompts | 6 | 38 |
| prep / action | 8 / 6 | 36 / 36 |
| requirements | 3 | 33 |
| memory / pr | 6 / 6 | 32 / 32 |
| orchestrator | 6 | 28 |
| offline_review | 5 | 27 |
| integration | 4 | 23 |
| integrations | 1 | 17 |
| skills | 3 | 15 |
| harbor / runtime / status_checks | 3 / 4 / 2 | 13 / 13 / 13 |
| workflow / instructions | 2 / 2 | 11 / 10 |
| reliability | 2 | 6 |
| yes / probe | 1 / 1 | 3 / 3 |
| e2e | 1 | 1 |

Directory names are not test levels. Many realistic multi-component and security tests are outside `tests/integration` and `tests/e2e`; the Docker scripts add another layer. Equally, 782 CI tests largely inspect workflow/config/script contracts, so they do not represent 782 real workflow executions. CI, docs and release together have **983 definitions (10.5%)**: useful configuration defenses, but they must be distinguished from product behavior.

Current coverage artifact totals: 56,604/64,390 statements; 16,961/21,864 branches; 7,786 missing statements and 4,903 missing branches. The combined percentage includes both statements and branches. Reported floors should be called combined coverage where appropriate, not line coverage.

| Production domain | Statement % | Branch % |
|---|---:|---:|
| action | 93.02 | 87.74 |
| agents | 90.00 | 81.47 |
| analyzers | 87.33 | 76.15 |
| browser | 32.18 | 5.26 |
| ci | 85.71 | 75.00 |
| classify | 97.89 | 93.72 |
| cli | 82.25 | 70.95 |
| config | 93.77 | 85.22 |
| context | 87.76 | 76.94 |
| enterprise | 91.32 | 80.67 |
| evals | 91.00 | 77.16 |
| evidence | 90.80 | 83.46 |
| findings | 91.77 | 82.68 |
| harbor | 0.00 | 0.00 |
| integrations | 96.67 | 88.46 |
| jev | 93.99 | 80.64 |
| mcp | 87.06 | 76.19 |
| memory | 84.44 | 57.69 |
| modes | 89.80 | 69.64 |
| orchestrator | 82.16 | 66.94 |
| policy | 89.99 | 82.98 |
| pr | 92.45 | 71.62 |
| prep | 80.58 | 61.02 |
| requirements | 95.91 | 84.38 |
| review | 89.59 | 75.35 |
| review_policy | 96.71 | 90.91 |
| scm | 87.70 | 58.55 |
| security | 89.27 | 80.20 |
| tracing | 88.14 | 83.73 |
| utils | 89.76 | 81.62 |
| verify | 89.14 | 82.00 |
| workflow | 82.84 | 78.41 |
| xrepo | 91.80 | 82.78 |
| yes | 54.88 | 25.00 |

Selected low **combined** coverage hotspots (at least 45 executable statements): `mcp/stdio.py` 17.14%; `browser/cdp.py` 18.04%; `mcp/xrepo.py` 20.41%; `analyzers/agentsec/skillspector.py` 25.30%; `cli/eval_cli_output.py` 47.14%; `cli/mcp_cmd.py` 47.56%; `yes/__init__.py` 47.69%; `mcp/dependencies.py` 50.96%; `cli/ask_cmd.py` 51.47%; `cli/lens_cmd.py` 54.55%; `cli/learnings_cmd.py` 54.63%; `cli/agent_cmd.py` 55.19%; `utils/diff_paths.py` 56.41%; `cli/gha_cmd.py` 58.87%; `analyzers/egress.py` 59.62%; `orchestrator/pipeline.py` 64.47%.

Interpret these carefully. MCP stdio has subprocess tests whose child execution is not fully attributed to the parent coverage run. Egress has a separate successful privileged lane. Harbor is an optional extra absent from the measured job. Low reported coverage is a reason to inspect a path, not proof that no test exists or that the feature is broken. The CLI/orchestration gaps are nevertheless relevant because these are user-facing composition paths.

## Quality of the oracles and fixtures

There are meaningful behavioral tests. `tests/e2e/test_policy_offline_review.py:174–229` constructs a real Git base/head fixture where a PR weakens a blocking policy and tries to waive itself. A scripted agent submits approve; the test checks the terminal tool result, effective request-changes verdict, base-rule provenance, absence of the self-waiver, and final evidence packet failure. This checks a consequential invariant across several real components. Its fixture manually assigns base/checkout provenance at lines 151–155, so it does not prove real source acquisition always supplies those values correctly.

`tests/integration/test_provider_failures.py` and `test_billing_404_failover_466.py` now exercise failover/retry/budget behavior as hermetic integration. They are not a file-presence sentinel. `tests/ci/test_integration_job_ran.py:143–175` actively forbids integration markers in CI meta-tests and checks that the real hermetic files are selected. The separate privileged lane's ten passing cases make root UID/ownership/egress assurance substantially stronger than a suite that simply skips everything on ordinary runners.

Structural tests have appropriate uses and limits. `tests/ci/test_wheel_contents.py:58–69` pins the exact exclusion list in pyproject. That stops unreviewed packaging drift; it cannot establish that the list is safe. Its docstring claims installed CLI help checks in a scratch virtualenv, while the invoked script only tests one convergence import with development dependencies available. That mismatch is actionable below. Similarly, checking workflow YAML for a command or permission is valuable but does not show that the command runs against the intended artifact or produces the intended decision.

The coverage run selects coverage-marked tests that ordinary `make test` excludes (`Makefile:163–165`, `pyproject.toml:261`). Nine files carry this marker, across CLI auth/analyzer branches, Codex/Gemini/OpenCode adapters, provisioning, SCM and agent resolution. Although the marker description literally says “branch-walking tests that inflate coverage,” sampled cases do assert behavior, such as permission-dependent home fallback, error classification and passing secrets through stdin. They should not be dismissed as fake tests. Their mocked external programs cannot prove current third-party CLI compatibility.

Known behavioral escapes show why covered functions need stronger input variation. The parent audit revalidated that a first-clause severity keyword can downgrade a real runtime error, and identical finding bodies can overwrite distinct row locations. `tests/findings/test_severity_rubric.py:14–47` largely pins the blocking set, verifies a positive cap, and checks the rubric exists/is structured data. Those are legitimate narrow tests; they do not test contradictions between cosmetic wording and explicit runtime failure. The mixed-severity analyzer cluster now preserves the strongest severity, fixing that specific September bug. A separate causality defect remains: a canonical row with `introduced_by_pr=false` can override an introduced Major row, changing a failing gate to success. The parent reproduced it through real base comparison and suppression in `plans/audit-2026-11-05-core-probes.py`; the main report covers that runtime finding.

The current mutation result adds an independent signal: enforcement survives 7/12 mutations; gates, finding dedup and status checks each survive 6/12. Twelve mutations per module are a small sample and may include equivalent mutations, so this is not a calibrated defect escape probability. Nevertheless, it is incompatible with calling every critical decision boundary thoroughly specified. The nonzero-exit bug below can only make that score look better than warranted.

Golden/replay evals mainly establish stable schemas, expected replay/scoring mechanics and internal consistency. CI now explicitly names the check “structural replay, not live detection,” which is honest. The live-image smoke verifies an actual terminal review on a one-line addition, with no running analyzers in the observed log. It does not establish detection on subtle bugs, false-positive rates, finding location accuracy or agreement with human outcomes. Human labeling/calibration/incident-eval expansion is already open work, so this memo treats that limitation as a confidence boundary rather than a new duplicate issue.

## Findings outside the assumed-solved open work

### T1 — Mutation errors count as successful kills

- **Classification:** residual September defect, revalidated on current source; testing correctness.
- **Severity / confidence / effort / fix risk:** Medium / High / Small / Low.
- **Location:** `scripts/mutate_decision_modules.py:410–415`, baseline loop at `515–528`.
- **Trigger:** pytest exits 2, 3, 4 or 5 because collection, internal execution, arguments or selection failed. A baseline test failure is also not detected before introducing mutants.
- **Observed:** the production helper counted all four injected exit classes as `killed=1, errors=0`, even though the probe explicitly returned “pytest did not complete any tests.”
- **Impact:** a broken test environment or selection can generate an excellent mutation score without rejecting any changed behavior. Current CI marks this lane advisory, limiting immediate merge impact, but the quality signal is false.
- **Fix:** run and require a clean baseline for each selected test set; distinguish normal assertion failure from interrupted/internal/usage/no-test exits; surface invalid mutants and infrastructure errors separately from killed mutants.
- **Validation:** assert clean baseline is mandatory and every pytest exit class is classified explicitly; add a deliberately broken collection case which must fail the harness, not improve its score.

### T2 — Action E2E passes an explicitly failing result on the wrong commit

- **Classification:** residual September defect, revalidated on current source; testing correctness.
- **Severity / confidence / effort / fix risk:** Medium / High / Medium / Low.
- **Location:** `docker/e2e/assert_e2e_outputs.py:113–128`; canned provider `docker/e2e/fake-provider-cli/claude:6–14`; invocation `docker/e2e/run_action_e2e.sh:73–79`.
- **Trigger:** a result contains the canned success phrase and a completed check-run has the required keys, but the conclusion is failure or the head SHA is wrong.
- **Observed:** `main()` accepted `head_sha='WRONG-COMMIT'`, `conclusion='failure'`, title `Failure`, summary `No review accepted`, and returned 0. The canned provider ignores all arguments, does not perform checkout or terminal submission, and the invocation disables analyzers.
- **Impact:** the built-image smoke can be green when publication addresses the wrong commit or produces a failing check. The observed nightly fake run also reported a neutral/require-human-review shadow decision while the shape test passed. This does not invalidate the separate real offline live smoke, but that smoke does not publish a GitHub PR either.
- **Fix:** assert the expected commit and exact expected semantic conclusion/output; drive a deterministic fake CLI through the actual MCP checkout and terminal submission protocol; add malformed, wrong-SHA and failed-publication negative cases.
- **Validation:** the reproduced wrong-SHA/failure body must fail; a clean complete deterministic Action review should pass and persist the expected review/check record.

### T3 — Installed-wheel acceptance is narrower than its claimed contract

- **Classification:** partially fixed September gap with a current documentation/test-contract mismatch; release assurance gap, not a demonstrated broken wheel.
- **Severity / confidence / effort / fix risk:** Medium / High / Medium / Low.
- **Location:** `scripts/check_wheel_corpus.py:17–44`; `tests/ci/test_wheel_contents.py:9–12`; release-only wiring `.github/workflows/ci-cd.yml:91–112`; `Makefile:487–488`.
- **Trigger:** a packaging exclusion, console entry-point issue or undeclared runtime dependency affects an installed CLI route outside convergence replay.
- **Observed:** the gate installs with `uv pip install --target ... --no-deps`, then uses the existing development interpreter with `-I`. This isolates cwd/user site, but keeps that interpreter's installed dependencies. It imports the wheel's package and convergence replay only. There is no fresh virtualenv and no `mergecraft --help` or `mergecraft eval --help` call, despite the test docstring claiming both.
- **Impact:** missing runtime dependencies or broken CLI routes can evade the acceptance check. PR CI builds the distribution but does not run this release-only acceptance script.
- **Fix:** use a fresh environment resolving only declared wheel dependencies, run console entry points outside the checkout, exercise representative offline routes and import all shipped command modules; run this against PR-built wheels as well as release candidates. Correct the docstring until the stronger proof exists.
- **Validation:** the isolated test must fail for a deliberately missing console-entry dependency or excluded CLI-imported module, and succeed without repository files on the import path.

### T4 — Bootstrap can repair a stale lock before the lockfile gate inspects it

- **Classification:** residual September defect; CI reproducibility.
- **Severity / confidence / effort / fix risk:** Medium / High / Small / Low.
- **Location:** `.github/actions/bootstrap/action.yml:27–35`, `Makefile:44–45`, `.github/workflows/ci.yml:91–95`.
- **Trigger:** pyproject and the committed uv.lock drift.
- **Evidence:** bootstrap executes ordinary `uv sync --extra dev` before the later `make lockcheck`. Sync is allowed to update the lock, so the gate checks a repaired workspace rather than necessarily the committed lock. Docker builds use frozen dependency resolution, exposing the mismatch later.
- **Impact:** the nominal lock gate can pass after mutating the evidence it is meant to validate. The two toolchain/lockcheck statuses are not required in the actual main ruleset either.
- **Fix:** bootstrap with locked resolution or run lock validation before any mutating resolution; assert no lockfile diff after setup as a secondary check.
- **Validation:** a PR fixture with an intentionally stale committed lock must fail before dependency installation silently rewrites it.

### T5 — Fresh Linux ARM64 workflow-lint selects an archive incompatible with its digest

- **Classification:** newly identified current portability defect; developer tooling.
- **Severity / confidence / effort / fix risk:** Low / High / Small / Low.
- **Location:** `scripts/workflow_lint.sh:9–10,22–24,36–38`.
- **Trigger:** run workflow-lint on Linux aarch64/arm64 with no cached actionlint executable.
- **Evidence:** architecture selection downloads `actionlint_1.7.12_linux_arm64.tar.gz`, while the checksum variable is the single amd64 digest. Unlike the later zizmor section, actionlint verification has no architecture-specific branch. Distinct architecture archives cannot share that digest.
- **Impact:** a path the script explicitly accepts fails checksum verification before linting. The zizmor arm64 path at lines 52–56 also skips checksum verification entirely, despite the script's top-level claim that both downloads are SHA-pinned.
- **Fix:** define verified per-architecture digests for both tools, or explicitly reject unsupported architectures. Avoid implying validated ARM64 support until that lane exists.
- **Validation:** test URL/digest selection for amd64 and arm64 without downloading during the unit test; add a Linux ARM64 smoke if support is promised.

## Enforced CI, platforms and artifact boundaries

GitHub API inspection of current rulesets, rather than inference from workflow names, found **nine required status contexts** on main: static/build on Python 3.11 and 3.14; all four unit shards; both security audits; coverage on Python 3.14. Active rulesets are `protect-main` (19969460) and `require-ci-on-main` (21652574). A PR needs one approval, code-owner review, latest-push approval, dismissed stale reviews and resolved threads. Force pushes/deletion are forbidden. Strict up-to-date status enforcement is false.

Integration, root privilege, E2E, CodeQL, deployment-candidate verification, toolchain/lockcheck and the structural eval gate are **not required contexts** in that ruleset. Mutation and shadow comparison are explicitly advisory. Absence from required contexts does not mean those workflows never run or that failures are ignored by a human. It means the repository's configured merge gate does not itself guarantee they passed. CI/CD image building separately requires its verify and E2E dependencies.

All inspected main runtime matrices use `ubuntu-latest` (amd64), Python **3.11 and 3.14**. Testing the declared lower bound and current upper endpoint is good. Python 3.12/3.13, native macOS, Windows and ARM64 are not exercised by these matrices. Documentation `docs/compatibility-matrix.md:17` lists Linux amd64 and arm64 with a qualifier, while line 64 says arm64 expansion is still tracked. There is no current multi-platform build declaration in the inspected image jobs, and the full analyzer Dockerfile downloads x86_64-specific tools. The supported/runtime/tested distinction needs to be explicit.

The current Integration skips are understandable and should be disclosed: Harbor optional-extra cases, a real OpenCode configuration-isolation test when the required CLI is absent, and privileged egress cases on the ordinary runner. The latter have a successful separate root lane; they are not simply untested. Browser and Harbor functionality remain poorly represented in the main coverage result. The live-provider matrix is now honest about only GitHub credentials there; the image live slice covered one OpenCode model in the observed run, not Anthropic/OpenAI/Gemini HTTP APIs or all harnesses.

Security defense has useful layers: Bandit/dependency audits, workflow scanners, CodeQL, in-image adversarial tests, root privilege checks, image scans, signatures/provenance and candidate validation. The current dependency advisory is excluded as assumed-solved open work. CodeQL no longer discards analyzer failures. The full analyzer image still invokes `uv sync --frozen --no-dev` without the slim image's tracing extra (`Dockerfile.analyzers:169`), so image flavor parity deserves an explicit test if tracing is a supported feature in both. This memo does not claim every security lane is an enforced merge status.

## September finding reconciliation

| Prior concern | Current disposition |
|---|---|
| Integration gate satisfied by a CI file-existence sentinel | **Fixed.** Meta-tests cannot carry integration markers; real hermetic cases execute (19 passed in current standard lane). |
| CodeQL analysis failures ignored | **Fixed.** Current workflow does not continue on analyzer error; upload is conditionally permitted by event/repository context. |
| Release prepare pushes with GITHUB_TOKEN but no downstream build runs | **Fixed.** release.yml explicitly dispatches CI/CD with actions:write; build-dist accepts dispatch on release refs. |
| Release metadata/version drift | **Fixed.** preReleaseCommand uses the version script updating project, server/package metadata and root lock package together. |
| SHA-pinned Craft wrapper installs unrelated latest executable | **Fixed at current upstream pin.** The exact pinned Action calls a resolver deriving version from SHA/package metadata, verifying matching tag and published release, or selecting the matching nightly SHA. [Pinned resolver](https://github.com/getsentry/craft/blob/0ff75896d43285ca376c7254e8143bac23acd429/.github/scripts/resolve-craft-version.sh). |
| No installed-wheel gate | **Partially fixed.** Release dist invokes convergence install-check, but isolation and CLI smoke claims remain incomplete (T3). |
| Mutation infrastructure failures scored as kills | **Still present, re-proved** (T1). |
| Action E2E accepts wrong SHA/conclusion | **Still present, re-proved** (T2). |
| Bootstrap mutates lock before validating it | **Still present** (T4). |
| Only fixed-seed execution | **Improved.** The nightly randomized run has current passing hosted evidence. |
| Mixed-severity dedup loses blocking severity | **Severity preservation fixed, per parent reproduction.** Separately, canonical-row causality can still suppress an introduced Major finding; see the main report and core probes. |

## Reproduction and measurement notes

Inventory command (read-only):

```python
import ast, collections
from pathlib import Path
stats = collections.defaultdict(lambda: [0, 0, 0])
for p in Path('tests').rglob('test_*.py'):
    source = p.read_text()
    tree = ast.parse(source)
    tests = [n for n in ast.walk(tree)
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
             and n.name.startswith('test_')]
    parts = p.relative_to('tests').parts
    domain = parts[0] if len(parts) > 1 else '(root)'
    stats[domain][0] += 1
    stats[domain][1] += len(tests)
    stats[domain][2] += len(source.splitlines())
print(dict(stats))
```

Coverage was downloaded in memory with `gh api --allow-escape-sequences repos/alexhawat/mergeCraft/actions/artifacts/13448484775/zip`; Python's `zipfile.ZipFile(io.BytesIO(...))` read `coverage.json`. Domain rows sum each file's `num_statements`, `covered_lines`, `num_branches`, `covered_branches` before computing percentages. No source files, environment or dependency state were changed.

The [testing probe](https://github.com/alexhawat/mergeCraft/blob/5dbaa2d4f59f321ec675b499e6a16e2421711d07/docs/dev/plans/audit-2026-11-05-testing-probes.py) exercised T1 and T2 using the standard library and in-memory writes. The script was removed after verification in #1273. The audit used the following technique.

```python
from pathlib import Path
import importlib.util, sys, argparse

def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    obj = importlib.util.module_from_spec(spec)
    sys.modules[name] = obj
    spec.loader.exec_module(obj)
    return obj

m = module('audit_mutation', 'scripts/mutate_decision_modules.py')
class MemoryPath:
    def read_text(self, **kwargs):
        return 'def eligible(value):\n    return value == 1\n'
    def write_text(self, value, **kwargs):
        return len(value)
m.resolve_module_path = lambda *args, **kwargs: MemoryPath()
m._module_test_dirs = lambda: {'fixture.py': ('tests/fixture',)}
for exitcode in (2, 3, 4, 5):
    m._run_pytest = lambda *args, exitcode=exitcode, **kwargs: (
        exitcode, 'pytest did not complete any tests')
    result = m._mutate_module('fixture.py', sandbox_root=Path('/unused'),
                             python=Path('/unused'), max_mutants=1,
                             seed=1, verbose=0)
    print(exitcode, result.killed, result.errors, result.survived)
# Each output: <exitcode> 1 0 0

e = module('audit_e2e', 'docker/e2e/assert_e2e_outputs.py')
class FakePath:
    def is_file(self): return True
args = argparse.Namespace(github_output=FakePath(), check_runs_dir=FakePath(),
                          expect_outcome='passed', require_check_runs=True)
e.argparse.ArgumentParser.parse_args = lambda self: args
e._parse_github_output = lambda path: {'result': 'E2E review complete: no findings.'}
e._load_check_runs = lambda path: [{'body': {
    'name': 'mergecraft', 'head_sha': 'WRONG-COMMIT', 'status': 'completed',
    'conclusion': 'failure', 'output': {'title': 'Failure', 'summary': 'No review accepted'}
}}]
print(e.main())  # 0, despite wrong commit and failure conclusion
```

Read-only hosted inspection commands were `gh api` for exact run/job metadata and narrowed job logs, `/repos/alexhawat/mergeCraft/rules/branches/main`, `/rulesets?includes_parents=true`, and releases. Actual scheduled live calls were made by the repository's prior jobs, not by this audit. Current test counts, coverage and platform statements are bounded by those specific runs and files.
