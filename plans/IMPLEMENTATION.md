# Implementation record

Implementation is in progress on `codex/implement-issue-remediation-20260922`, in `/private/tmp/mergecraft-implementation-20260922`. The original checkout and its existing configuration edit are preserved. The initial wave used three faster `gpt-5.6-sol` executors; subsequent work is assigned to the available `gpt-5.6-luna` model. The coordinator reviews and integrates their commits.

## Baseline and scope

- Original audit: main `be9993367386b03f982c795ceb1d80e4a0bfcf1d`.
- Implementation started from main `d77511cb93438c064c83d50ffdb9228136e8996b` (merged #818), then integrated main `41cf53b3` (merged #817).
- Integrated main `e79217be` after plan PR #826 merged. Its plan contents exactly matched the originally cherry-picked plans; the merge retains subsequent implementation refinements and adds no source drift.
- The first source scopes (001/002/004/005/007) did not drift. #818 changed strict analyzer test handling, which is accounted for in new plan 016. #817 changed coverage floors; plan 006 must use the merged baseline and a new attributable final measurement.
- Human labels, chosen live models/budgets, candidate-specific release verification and publication remain separate completion criteria. Synthetic tests do not satisfy them.

## Current verification state

- The complete unsharded baseline at source `157f57a3` passed: **10,025 passed, 16 skipped, 22 deselected, 4 xfailed**, with 17 warnings in 3,462.87 seconds. Native combined coverage is **83.28103063836815%**, above the unchanged 82% floor. Python 3.14.6, coverage 7.15.2, pytest 9.1.1, seed 424242, selection `not integration`. The saved JSON SHA-256 is `1f54f759d1f77d8f318268e6ee4afe46227703e19b77998a4ffcb47cb2cb5b2c`; JSON/raw data and runtime/source receipts are retained in `/private/tmp/mergecraft-remediation-validation-20260922/`. Three plan files were temporarily edited and restored during measurement; Python, test and coverage configuration inputs remained unchanged.
- Combine-time source/runtime drift checks (`157f57a3`) passed 38 focused executor tests. The first whole-shard attempt was unsuccessful: group 1 reported **1 failed, 5,011 passed, 9 skipped and 3 xfailed**; group 2 was interrupted after **3 failed, 1,037 passed and 3 skipped**. Nested standalone gate fixtures inherited outer shard variables. Reviewed test-only cleanup is integrated as `daaa613c`; failed or interrupted artifacts are retained for diagnosis and are not accepted as parity evidence.
- Reviewed Loguru capture lifetime fixes are integrated as `24990993` and `c241c426`. Tests now drain and remove their own queued sinks before captured streams close and preserve existing process handlers.
- Issue #829 was reproduced during the full measurement: 2,814 generated analyzer cache files in the persistent hostile fixture were treated as untracked source. The reviewed fix is integrated as `021dd273`; generated cache entries are excluded before reads and per-file Git calls, while ordinary source/configuration and tracked changes remain eligible. The executor's exact changed test files passed 15 tests; the coordinator's exact-file offline diff, init and hostile-corpus checks passed **29 tests in 58.46 seconds**.
- The baseline measurement precedes these test-isolation and cache fixes. Measured thresholds are integrated as `4abd9199`; their counts and buffer formula were independently checked, and the executor passed 31 focused coverage tests plus both policy checks against the saved report. Final default `make ci` and fresh complete shard/unsharded parity remain pending. Final CI will supply the unsharded side of the same-source comparison; concurrent isolated shard measurements supply the other side. Its report must be preserved before combination writes the final report, avoiding an unnecessary third unchanged full run.

A final validation attempt at `4abd9199` passed static checks, both type checkers, package/docs generation checks and security. Normal CI and group 1 then exposed the same old fixture defect: `test_coverage_hh._coverage_json` labelled a module as 96% covered but truncated 9.6 covered branches to 9/10 (90%), below the correctly raised 91.2% token floor. The test-only correction is integrated as `cbdf2b0c`: fully covered modules isolate the global 82% contract. The coordinator reran both exact coverage fixture/floor files: **11 passed, 1 expected skip** because no previous root coverage report exists. The three test runs were interrupted after diagnosis (CI: 1 failed/920 passed; group 1: 1 failed/1,584 passed; group 2: 1,556 passed). These incomplete runs do not satisfy final CI or parity. Production floors are unchanged by this test-only correction.

### Completed integrated validation and parity follow-up

At frozen source `68e56cd9405d4512b8963113f7a8140af8f01c1a`, default `make ci` passed all static, type, build, documentation, security and coverage gates: **10,033 passed, 16 skipped, 22 deselected, 4 xfailed**, with 17 warnings in 2,461.51 seconds. Native combined coverage was **83.2872338961593%**. Both complete isolated shards also passed (group 1: 5,015 passed/10 skipped/3 xfailed; group 2: 5,018 passed/8 skipped/1 xfailed), with an exact, disjoint union of 10,051 selected nodes. The official `make coverage-combine-gate` passed source/runtime/collection validation, ratchet and every coverage floor; combined coverage was **83.29549051177256%**.

Exact per-file parity nevertheless failed: the shards covered two additional lines and four additional branches in doctor credential detection, run-manifest tracing configuration, shell Git-directory fallback protection and empty owned-workspace cleanup. Both gate decisions passed, but this difference does not satisfy plan 008's exact comparison. Test-only commit `70c5d6c8` exercises those paths explicitly and removes timing dependence from a socket shutdown/error regression. No production behavior or threshold was relaxed. Independent validation of all five affected test files passed **293 tests**, with four warnings in 54.89 seconds. A fresh same-source default CI and complete two-shard comparison will verify the final test changes.

All receipts remain under `/private/tmp/mergecraft-remediation-validation-20260922/`: `final-v2-ci.log`, `final-v2-unsharded.json`, `final-v2-parity-shards/`, `final-v2-combine.log`, `final-v2-combined.json`, `final-v2-parity-differences.json`, and `stability-focused.log`. Earlier failed attempts remain diagnostic evidence only.

## Release inventory (plan 015)

Read-only GitHub inventory on 2026-09-22 found:

- #783 remains open with no accepted label and all six publication targets unchecked.
- `release/0.1.0a2` still names `f98db2a522015b065c50bb451719052387a8a061`.
- No `v0.1.0a2` tag and no GitHub releases were returned.
- [Candidate run 35489981575](https://github.com/alexhawat/mergeCraft/actions/runs/35489981575) failed Full verify; Python distribution, Action E2E, image build, scan, signing, provenance verification and promotion jobs were skipped.
- GHCR package-version inventory returned HTTP 403 because the available GitHub credential lacks `read:packages`. Image/version collision state is therefore **unknown**, not clear. No credential changes were requested for this pending release step.
- No fresh release candidate has been selected: the implementation is still underway and unmerged. No prepare, publish, tag, accepted-label or live-provider action has run.

Before publication, the operator must select a fresh source/version and supply successful candidate-specific CI/image/signature, scheduled integration/security and adoption receipts. The verified source → digest → manifest → consumer pin chain remains required. The old failed request cannot approve a new source.

## Verification

The 85 audit/probe tests in VERIFICATION.md describe the original bugs and are not verification of these fixes. The coordinator independently inspected the integrated diffs and ran the following focused checks with the fresh isolated development/tracing environment (seed 424242 unless stated):

| Plans | Integrated commits | Independent result |
|---|---|---|
| 002 finalized verdict | `a648bef2` | 77 passed across terminal submission, verdict policy/harness and publication body tests |
| 003 reviewer/Git tokens and revocation | `a51188bd`, `9e8b327e` | 56 passed across token, Action phase and trust ordering tests |
| 004 publication retry | `10130b5e` | 32 passed across outcome, anchor recovery and real MCP review tests |
| 001 persistence redaction, 017 ordinary filenames | `9c101677`, `9afaacec` | 248 passed across trajectory/read coverage/packet and five analyzer-redaction test files |
| 005 exact successful-read attribution | `a0af80d9`, `6e2e09ed` | 292 passed across the same eight evidence/redaction files, including literal colon Git pathspec regression |
| 006 true line and branch coverage | `0b804ab8` | 47 passed across seven coverage CI files; numeric floors unchanged; final full measurement pending |
| 007 adjudication round-trip and corpus synchronization | `e1bb753f` | 117 passed; eval corpus sync check, structural/adversarial gate and installed-wheel convergence passed |
| 008 isolated coverage shards | `b2a899ee` | 33 passed, including real xdist/split fixture parity, manifest tampering/incompleteness, source drift and failure propagation; final whole-tree parity pending |
| 009 complete lifecycle tracing | `327a6d2c` | 410 tracing tests passed, plus 12 HTTP tracing tests with loopback access; real Docker OTLP collector passed 7 pre-seed and 2 post-seed tests (wrapper seeds 3886865826 and 3250636949) |
| 012 offline trajectory scorer | `7d384ac9` | 80 passed across scorer, trajectory and run-packet tests; development fixtures remain advisory, with human protocol/enforcement pending |
| 013 offline judge calibration | `ddd442d3` | 102 protocol, scoring, provenance/seal and CLI tests passed; actual independent human labels and held-out validation remain pending |
| 011 human review preparation | `ec2481f6` | 14 strict manifest/evidence tests passed; rendered [nine-case review sheet](HUMAN-REVIEW.md), all evidence missing and decisions unanswered |
| 010 complete setup artifact instructions | `3ffdd697` | 42 existing setup/documentation tests passed |
| 016 visible provisioning failure causes | `0edae3fb` | 68 adapter, contract, supply-chain, provisioning and sandbox tests passed |
| 014 offline benchmark publication | `e79fdeec` | 66 publication, receipt, live-boundary and calibration tests passed; one expected xfail for still-unpublished live metrics |

The table records focused checks; the completed integrated CI and pending exact-parity follow-up are recorded above. The initial redaction-check command named a nonexistent test file and ran no tests; the corrected exact-file invocation above completed successfully. The baseline generated-documentation check also passed.

Issue #827 was filed during implementation after a deterministic reproduction showed that the shared redactor masked the shipped doctrine filename. The central correction preserves bounded ordinary uppercase identifier components while existing high-entropy and credential-prefix tests remain green; trajectory persistence never restores redactor-removed values.

Issue #828 was filed for installation-token revocation reporting success without checking the HTTP response. The fix checks the status, keeps cleanup best effort across all owned tokens, and tests rejected revocations without leaking credentials.

The first tracing run could not bind its local HTTP server under the sandbox; the affected 12-test file was rerun with loopback access and passed. The supported Docker collector target completed successfully and cleaned up its test container. These checks establish trace transport and parenting, not a live provider evaluation.

An intermediate integrated `make ci-static` passed lock/lint, both type checkers, catalog and agent checks, package build, examples and CLI examples. It stopped at the expected generated CLI reference drift for the newly added calibration command; final generation is deferred until all new commands are integrated. The intermediate `make security` passed (no medium/high Bandit findings and no known dependency vulnerabilities). These results do not substitute for the final combined-tree gate.

A final independent review reproduced source drift during combine-time test collection in plan 008. The existing shard-time checks did not cover this boundary. The plan is refined to recheck the validated source/runtime identity after collection and around combination/reporting/gating, with mutation regressions before the complete measurement.
