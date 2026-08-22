# Eval methodology

How mergeCraft measures review quality. **This page does not replace #140.**
Issue #140 owns publishing precision, recall, and F1; this page documents the
wider metric set, the ablation harness, and the corpora those numbers are
computed against.

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

The analyzer-contribution ablation uses the **current** shipped analyzer
catalog as its baseline inventory. The #339 coverage sweep added analyzers;
do not freeze a pre-sweep count.

APIs: `mergecraft.evals.corpora`, `mergecraft.evals.quality_metrics`,
`mergecraft.evals.ablation`.

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

## Ablations

`mergecraft.evals.ablation.run_ablation` names these dimensions:

- multi-agent vs single-agent
- verifier contribution
- judge contribution
- context-engine contribution
- analyzer contribution (current catalog baseline)
- memory contribution

Each specialist can be evaluated independently by requesting that dimension.
Adversarial corpora are not an ablation dimension.

Unmeasured deltas stay at `0.0` with `measured=False`. A zero is "not yet
run", not "no contribution".

## What this page will not do

- Publish precision / recall / F1 as a product claim — that is #140.
- Put scores on `README.md`.
- Claim a ranking against other tools without a number on the same line as
  the claim, backed by a recorded result set.
