# CI results as analyzer / gate evidence (#36) — test plan

Wave plan: `.ignorelocal/waves/issues-analyzer-ci-evidence-wave-plan.md` (Batch C, W5–W6)
Worktree: `mergecraft-anz-c-ci-evidence` @ `wave/anz-c-ci-evidence`

Companion to [`ci-intelligence.md`](ci-intelligence.md), which covers the layer this
one consumes: normalisation, clustering, flaky classification, and blame. This plan
covers what happens to those signals *afterwards* — how a finished CI outcome becomes
a `Finding` and when it may change a gate's reported outcome.

## Test files

| File | Covers |
|------|--------|
| `tests/ci/test_evidence.py` | The pure contract: check run → `Finding`, SARIF → `Finding`s, declared-mapping resolution, substitution, truncation + redaction, recording round-trip |
| `tests/ci/test_evidence_seams.py` | The runtime seams: `run_static_checks`, `analyze_ci_failures`, and the end-of-run merge evidence packet |
| `tests/test_runtime_call_sites.py` | Drift guard — the three CI-evidence entry points must stay reachable from `main.py` / `cli/app.py` *and* stay wired into the tools a review actually calls |

No `xfail` markers survive: the suite was authored red against the pre-change tree
(both modules failed to import, since `mergecraft.ci.evidence` did not exist) and is
green as of W6.

## Substitution decision matrix (D10)

Read left to right; the first row that matches decides. "Declared" means the repo's
`ciEvidence.gates` maps this gate name to this exact check-run name.

| Gate row status | Declared? | Check-run conclusion | Result |
|---|---|---|---|
| `passed` / `failed` / `timed_out` | any | any | **Unchanged.** A verdict produced here outranks any CI claim about it |
| `unavailable` / `declared-but-cannot-run` | no | any | **Unchanged.** Undeclared CI is context, never gate satisfaction |
| `unavailable` / `declared-but-cannot-run` | yes | `success` | **`satisfied-by-ci`** — the row is *replaced*, never duplicated, and names the check run + URL |
| `unavailable` / `declared-but-cannot-run` | yes | `failure` / `timed_out` / `action_required` | **Unchanged row**, plus a recorded `source: ci` finding |
| `unavailable` / `declared-but-cannot-run` | yes | `skipped` / `neutral` / still running | **Unchanged.** No verdict to borrow |

The second row is the security-relevant one: `test_gate_substitution_requires_a_declared_mapping`
uses a check run named *exactly* like the gate and asserts the similarity buys nothing.

## Blame matrix for CI-derived findings (D11)

| Source | Severity | `introduced_by_pr` | Can block? |
|---|---|---|---|
| Bare check run (no retry history, no base comparison) | `Minor` | `unknown` | No |
| SARIF artifact from the consumer's CI | capped at `Minor` | `unknown` | No |
| Clustered failure, `annotate_not_caused_by_pr` (flaky / pre-existing) | `Minor` | `false` | No |
| Clustered failure, `annotate_caused_by_pr` (diff overlap) | `Major` | `true` | Yes |

"Can block" is not a description — it is the property under test. Every consumer of
findings (`agents.gates.decide_approval`, the merge evidence packet's verdict) is
monotone in `BLOCKING_SEVERITIES = {Critical, Major}`, so keeping flaky failures at
`Minor` is *the* mechanism behind "reported, not blamed". Covered by
`test_flaky_ci_finding_never_blocks_the_approval_gate` and
`test_flaky_ci_finding_does_not_flip_the_packet_verdict`, with
`test_pr_attributed_ci_finding_does_block_the_packet_verdict` as the mirror image so
neither assertion can pass vacuously.

## Runtime seams (the #96 lesson)

Structural tests are not sufficient evidence: `build_packet`, `write_packet` and
`classify_blast_radius` all shipped with thorough unit tests and no consumer. Each
CI-evidence entry point therefore has a named runtime call site, asserted by module:

| Symbol | Called from | What breaks silently without it |
|---|---|---|
| `substitute_declared_gates` | `mcp/static_checks.py` | A gate the consumer's CI proved goes back to reporting `unavailable` |
| `record_ci_findings` | `mcp/static_checks.py`, `ci/intelligence.py` | A CI outcome never becomes a `Finding` |
| `ci_evidence_findings` | `evidence/run_packet.py` | Recorded CI evidence never reaches the packet |

Both seams hang off MCP tools the Review / IncrementalReview prompts name in their
checklists (`run_static_checks` in step 2, `analyze_ci_failures` when CI failed on the
head), so reachability is not merely theoretical.

## Redaction (convention 8)

`ci_evidence_lines()` truncates to the *tail* of an excerpt (a build log's informative
part is where it died), clips each line, caps the total, and passes every surviving
line through `analyzers/redact.py`. `tests/ci/test_evidence.py` plants
`tests/ci/support.CANARY_SECRET` in both a raw excerpt and a check-run finding and
asserts it never appears in the message or the evidence list.

## Failure modes deliberately made non-fatal

| Failure | Behaviour | Test |
|---|---|---|
| GitHub check-runs API error | Gate report returned untouched | `test_github_failure_leaves_the_gate_report_unchanged` |
| No head SHA on the run | No substitution attempted | covered by the early return; no API call |
| Unreadable / non-SARIF artifact archive | Logged, ingest returns what it has | `_sarif_documents` swallows `BadZipFile` |
| Malformed recorded finding row | Dropped at read time, packet still built | `ci_evidence_findings` |

## Out of scope

- Fuzzy matching of CI check names to gates (D10).
- Extending `Finding` (D12) — CI evidence uses `evidence` and `source`.
- Uploading anything *to* GitHub; that is #39 / Batch D.
- Non-GitHub CI providers, which remain honestly stubbed.
