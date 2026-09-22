# Eval methodology

How mergeCraft measures review quality. **This page does not replace #140.**
Issue #140 owns publishing precision, recall, and F1; this page documents the
wider metric set and the corpora those numbers are computed against.

Scores are **not** published on the landing `README.md` (file 7 RD4 /
`test_no_eval_scores_on_landing_readme`). Live-provider numbers belong here
or in machine-readable result sets under `evals/results/` once a run exists.
Until a result set is recorded, treat every quality claim as unmeasured.

## Corpora

Three banks, kept separate on disk:

| Bank | Path | What it is |
|------|------|------------|
| Human-reviewed golden PRs | `evals/cases/golden/` | Reference cases across languages and frameworks |
| Synthetic mutation | `evals/cases/mutation/` | Generated defects; never mixed into golden |
| Adversarial | `evals/cases/adversarial/` | Prompt-injection and hostile shapes — **out of scope for #384** |

Golden categories: correctness, security, API breakage, concurrency, migration,
performance, dependency, and **clean** PRs (expected empty blocker set).

Extra benchmark kinds (also packaged): historical PR, cross-repo (`xrepo`),
requirements, large-PR, and incremental-review.

APIs: `mergecraft.evals.corpora`, `mergecraft.evals.quality_metrics`.

### Authoring and packaged copies

`evals/cases/` is the only authoring tree for the package-backed `golden/`,
`mutation/`, and `skill/` corpora. After editing or adding a case, run
`make eval-cases-sync`, review both the authoring file and its copy under
`src/mergecraft/evals/cases/`, then run `make eval-cases-sync-check`. The sync
is one way and does not delete stale packaged-only files; deleting a case
requires an explicit reviewed deletion from both trees.

At runtime, `mergecraft.evals.corpora` loads an explicit cwd-relative
`evals/cases/<kind>` directory first, packaged wheel resources second, and the
checkout-relative authoring tree last. `mergecraft eval adjudicate` changes
only the path passed by the operator. It does not infer or update another copy,
an installed wheel, or an unrelated custom corpus.

### First human adjudication batch

`evals/adjudication/golden-batch-001.json` is the strict preparation manifest
for the nine golden rows tracked by #780. Render its review sheet with:

```bash
make eval-human-batch
```

### Judge calibration

Label provenance only determines whether labels are eligible for scoring. It
does not establish that the verifier judge is calibrated. A judge-calibration
report requires frozen, disjoint calibration and held-out splits containing
saved verifier verdicts paired with independent human references.

```bash
make eval-judge-calibration \
  JUDGE_CALIBRATION_PROTOCOL=/path/to/protocol.json \
  JUDGE_CALIBRATION_CASES=/path/to/cases.json \
  JUDGE_CALIBRATION_SEAL=/path/to/candidate-seal.json
```

The command is keyless and reads saved verdicts only. It verifies case hashes,
judge/model/rubric pins, deterministic checks, human provenance, split class
coverage, and every explicit threshold. Without an externally created seal it
returns a provisional calibration-only report and does not score the held-out
split. There is currently no qualifying human-labelled dataset in this
repository, so the real held-out run remains pending. Test fixtures exercise
the protocol without being presented as human decisions.

The committed manifest names `alexhawat` as the intended adjudicator, but all
nine rows remain `evidence_status: missing` and `decision: pending`. Repository
history shows that commit `3ff1bb39d6a5c2035c19c793131c493b591cf98d`
introduced the metadata files; it contains no source patch, originating
repository, PR, or immutable code snapshot and is therefore history, not
substantive evidence for the claims. The review sheet keeps every row visibly
unanswered. No row may receive human provenance until immutable evidence is
recovered and the named human supplies an actual decision.

The manifest validates source URLs as commit-pinned, confines any local
fixture to `evals/fixtures/golden/<case-id>/`, and verifies its SHA-256 before
rendering. This batch establishes neither judge calibration nor human-human
agreement, even after its provenance requirements are eventually satisfied.

## Metric set

Computed by `mergecraft.evals.quality_metrics.compute_quality_metrics` against
a locality-matched baseline (`mergecraft.evals.scoring.score_findings`):

| Metric | Meaning |
|--------|---------|
| Blocker precision | Fraction of Critical-severity findings that hit a baseline issue. `None` when the run reported no blockers — not published, never a fabricated number |
| Severity accuracy | Fraction of locality matches whose severity agrees with the baseline. `None` when there are no matches (including zero findings) — not published, never a fabricated 1.0 |
| Duplicate rate | Fraction of findings that repeat an earlier overlapping finding |
| Unsupported-finding rate | Fraction of findings that did not hit the baseline (unadjudicated on an open-world corpus) |
| Contradiction rate | Fraction of findings that overlap an earlier finding at a different severity |
| Time to first useful finding | Wall time to the first baseline-matching finding, or unset |
| P50 / P95 latency | Percentile review latency; an empty sample is an error, never a fabricated `0.0` |
| Cost per review | USD attributed to the review |

Empty findings yield `0.0` rates (honest-zero), never NaN. Blocker precision
and severity accuracy stay `None` when there is nothing to score.

Release *targets* (not yet measured here): blocker precision above 95%, a
materially higher recall than a strong single-agent baseline, a low duplicate
rate, and a demonstrable verifier/judge contribution. Those targets are
hypotheses until a live result set fills them.

## What this page will not do

- Publish precision / recall / F1 as a product claim — that is #140.
- Put scores on `README.md`.
- Claim a ranking against other tools without a number on the same line as
  the claim, backed by a recorded result set.

## Reproducible live campaign

`make eval-gate` and `make eval-replay` check structural case integrity and
replay expected decisions without a provider. They do not measure live detection.
Use `make bench-detect BENCH_DETECT_ARGS='--model PROVIDER/MODEL --detection-corpus PATH --results-dir PATH --json'`
once per chosen model against the same frozen, patch-bearing corpus. Record its
Git tree SHA, exact model, rubric/source pins, expected case count, executed
case count, errors, latency and cost alongside each result. A missing detection
section or zero executed cases is not benchmark acceptance. Failures must remain
visible, not be scored as clean reviews.

Start with a small corpus containing a labelled defect and a clean case. Obtain
a spend ceiling and provider/model choices before expanding to the full bank.
`MERGECRAFT_RUN_TIMEOUT_S`, `MERGECRAFT_COST_BUDGET_USD`, and
`MERGECRAFT_TOKEN_BUDGET` bound each review; the operator must also cap total
campaign size. Preserve raw case results for adjudication. Unmatched findings
remain unadjudicated when the reference labels are incomplete. Publish measured
results here or under `evals/results`, with a README link rather than unsupported
landing-page scores; reconcile #140's publication contract before closure.

`make test-wheel-corpus` installs the built wheel in a temporary target and
runs convergence outside the source checkout. This verifies packaging only.
The E2E workflow's optional real-harness smoke requires the trusted repository
variable `MERGECRAFT_E2E_LIVE_MODEL` and that model's credential. It permits one
180-second review with a 12,000-token, 30-tool-call and $1 reported-cost budget.
It runs the actual installed image harness and requires a terminal verdict;
it is not a quality score or a substitute for the two-provider campaign.

The initial two-case smoke selection is frozen in
`evals/bench/smoke-manifest.json` with SHA-256 hashes of each patch and label file.
Copy only those named case directories into the campaign corpus directory.
It contains one seeded boundary defect and one clean documentation change.
These are agent-seeded labels, not independent ground truth; independent
adjudication and model/rubric pins remain prerequisites for comparison claims.
No provider, spend authorization, or measured result is implied by this manifest.

The live image smoke accepts `openai/`, `anthropic/`, `google/` or `gemini/`
model prefixes and passes only the selected provider credential into the container.
Unknown providers or a missing selected credential fail before starting Docker.
