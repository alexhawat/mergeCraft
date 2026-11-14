# mergeCraft evals

Eval bank vs ReviewBench — what each mechanism measures and how to run gates.

**Audience:** satellite (scoped README for one directory)

ReviewBench-style benchmark infrastructure for mergecraft PR reviews.

## Two mechanisms, two jobs

These are often confused. They measure different things and belong in different places.

| | Eval bank (`evals/cases/`) | ReviewBench (`bench/review/`) |
|---|---|---|
| Question | *Did we break something we already fixed?* | *How good is the review?* |
| Source | real failures, via `mergecraft eval add` | frozen human-curated baselines |
| Cost | free, deterministic | one Docker environment per task |
| Gate | `make eval-gate`, plus promoted pytests in `make test` | `make bench-review`, periodic |

Use the **eval bank** for per-PR CI. Use **ReviewBench** to compare versions or
providers — never as a per-PR gate, regardless of corpus size.

## Status

The frozen task corpus is **not** vendored here — it lives in
[sevn-bot/tripll](https://github.com/sevn-bot/tripll) under `bench/review/`
(delivered by [tripll#64](https://github.com/sevn-bot/tripll/issues/64), closed).
Point at it directly rather than copying:

```bash
make bench-review REVIEWBENCH_DIR=../tripll/bench/review
```

It is currently **one Harbor task with two baseline issues**. That is enough to
prove the loop end to end and nowhere near enough to detect a quality regression
— scaling it means running tripll's `findings gate` / `findings promote` pipeline
over more merged PRs, which needs no new code here.

**Contamination warning:** tripll runs mergeCraft on its own PRs, so mining its
Finding graph can promote mergeCraft's own accepted findings into the baseline,
which it would then trivially rediscover. Every baseline row carries a mandatory
`provenance` field for exactly this reason. Keep `provenance: human` as the
primary corpus and report scores with and without the rest.

## Label eligibility bar

Scoring reports recall and precision for any corpus. Label provenance decides
whether those labels meet a configured eligibility bar. It does not establish
that a model judge is calibrated.

```yaml
adjudication:
  requireForCalibration: independent
```

Each label's `provenance` maps to an independence tier:

| `provenance` | Tier |
|--------------|------|
| `human` | `independent` |
| `jev-adjudicated` | `model` |
| `llm-adjudicated` | `model` |
| `agent-seeded` | `none` |

An unrecognised `provenance` string resolves to `none`, so a label can never
satisfy the bar by accident.

`requireForCalibration` accepts `independent` or `model` only. There is no
"no bar" setting: a zero bar would clear every provenance including
`agent-seeded`, which is precisely the claim configuration must not be able to
make.

Scoring still reports recall and precision for an agent-seeded corpus — the
numbers are real and useful for regression detection.
`ScoreReport.calibration.eligible` stays `False` unless every
label in the set meets `requireForCalibration`. One unadjudicated row is enough
to sink a corpus-wide claim, because a claim about the corpus is only as good as
its weakest label.

```text
  label eligibility: ineligible — 1 of 3 labels below the 'independent' bar
```

The same verdict is carried on `DetectionMetrics` so a persisted benchmark
result cannot show scores without it, and appears under the backward-compatible
`calibration` key in `eval score --json`.

A separate saved-verdict protocol measures judge calibration. It compares raw
`confirm|downgrade|drop` judge decisions with independent human references on
disjoint, hash-pinned calibration and held-out splits. Run it with
`make eval-judge-calibration JUDGE_CALIBRATION_PROTOCOL=... JUDGE_CALIBRATION_CASES=...`.
An externally supplied candidate seal is required before held-out metrics are
computed. No qualifying human-labelled paired dataset is committed yet, so no
validated judge-calibration claim is currently available.

## Adjudication

Who may assign a label is repo configuration; what the label is worth is the
calibration bar above. The two are answered separately so that enabling an
adjudicator can never by itself upgrade a claim.

```yaml
adjudication:
  adjudicators:
    human: { enabled: true,  independence: independent }
    jev:   { enabled: false, independence: model }
    llm:   { enabled: false, independence: model }
  requireForCalibration: independent
```

`enabled` is the approval gate: an adjudicator that is not enabled cannot label
cases. `independence` is recorded on the audit record; the tier used for
calibration comes from the derived `provenance`, never from this field.

Labels are written through `mergecraft eval adjudicate`, which is where the
policy is enforced:

```bash
mergecraft eval adjudicate baseline.json --id ISSUE-1 --by human
mergecraft eval adjudicate baseline.json --id ISSUE-1 --by llm --model judge-2 \
  --produced-by judge-1
```

Comment (`//`) and blank lines in a JSONL baseline are preserved: only the data
lines are rewritten, in place.

Baselines are envelopes — `{"closed_world": ..., "issues": [...]}` — and the
command rewrites the row in place, preserving every other key. Bare lists,
single-object documents, and JSONL are also accepted, and a JSONL input is
written back as JSONL rather than reindented.

An unapproved adjudicator exits non-zero and writes nothing. The row's
`provenance` is derived from the resulting record, never supplied by the caller.

A model adjudicator must name both `--model` and `--produced-by`. The check
fails closed on a missing identity: an unknown producer cannot be *shown* to
differ from the adjudicator, so omitting the argument is refused rather than
allowed. A human adjudicator carries no model identity and needs neither.

The command writes the adjudication record beside the derived `provenance`, so
the independence check leaves durable evidence rather than an unfalsifiable
claim:

```json
{
  "id": "ISSUE-1",
  "provenance": "llm-adjudicated",
  "adjudication": {
    "adjudicated_by": "llm",
    "model": "judge-2",
    "produced_by": "judge-1",
    "independence": "model",
    "at": "2026-09-19T15:04:21Z"
  }
}
```

**Self-adjudication is refused regardless of configuration.** A model may not
score labels its own pinned model produced; that is the circularity the corpus
already suffers from, and no config key waives it.

## Scoring

Score a run's findings against a baseline:

```bash
mergecraft eval score actual-findings.json ../tripll/bench/review/baseline.jsonl
```

A baseline issue counts as **located** when a reported finding overlaps its line
range in the same file — not when the two rows are equal. Equality scoring fails a
run for paraphrasing a finding it genuinely found, and cannot pass at all against
a corpus whose rows carry their own `rule_id` and `fingerprint`. Severity and
category agreement are reported alongside each match, never as match conditions;
corpus severity vocabularies (`high`/`medium`) are normalised onto
`FINDING_SEVERITIES` (`Major`/`Minor`) first.

`precision` here is **"how much of the output is corpus-confirmed"**, not a
false-positive rate: a real defect the human curator never recorded scores as
unmatched.

## Bank integrity

```bash
make eval-gate
```

This is **structural, not behavioural**. It proves every durable case still parses
against the current schema and provenance model and that ids are unique. It does
not replay verdicts: `replay_case()` is pure and takes the current decision as an
*input*, so replaying in CI would need a live agent run per case. The behavioural
signal is `mergecraft eval promote`, which turns a case into a permanent pytest
that `make test` already runs.

## Benchmark replay (W9)

Operator-triggered replay writes a versioned result set under `evals/results/`.
It is **not** wired into PR CI — live provider runs cost quota and need secrets.

```bash
make eval-replay
# or: mergecraft eval replay-bank --json
```

The multi-round convergence cases (`pr-216-eval-gate-matrix`,
`pr-250-memory-feedback`, `pr-253-scm-provider`) also carry replay inputs: their
`recorded_findings` are the findings the first review round raised on the real PR,
so structural replay recomputes a verdict for them (`failure`, a blocker was raised)
instead of leaving them `blocked`. A permanently blocked case counted as
inconclusive on every run, which put a fixed floor under `inconclusive_rate`
that no behaviour change could lower. Convergence across the later rounds is still
scored separately by `mergecraft eval convergence`.

Each result set records:

- `rubric_version` (`VERIFIER_RUBRIC_VERSION`)
- `judge_pins` per provider (default: Claude + OpenAI)
- S5 `mode_prompt_versions` for every built-in mode
- `corpus_commit` (git SHA of the case files)
- structural decision-replay pass rate across the bank

Finding-location **precision / recall / F1** and false-positives-per-run come
from a live run. With missing API keys the harness records `skipped: no live
credential` and omits those metrics — do not fabricate a table in the README.

`mergecraft eval bench` runs **one** provider/model per invocation — its
`detection` section is that single provider's result, not the full
comparison. **Publishing requires ≥2 configured providers** (D12: reported
per provider, never averaged) — run `eval bench` once per provider (each
call gets its own timestamped result set and raw-findings directory, so
nothing overwrites an earlier run's evidence) and combine the separate files
at publication time (B7). A single-provider result set committed along the
way is an honest partial artifact, not a claim that D12 is satisfied.

### Two corpora, two questions (D7)

`evals/cases/` (the bank above) and `evals/bench/mergecraft/` (below) answer
different questions and are never conflated:

| | `evals/cases/` (bank) | `evals/bench/mergecraft/` (detection corpus) |
|---|---|---|
| Question | *Did the gate make the right decision?* | *Did the review find the right lines?* |
| Ground truth | `recorded_findings` + `expected_decision`, no patch | a patch + `baseline.json` (`{"closed_world": bool, "issues": [...]}`) |
| Cost | free, keyless — `replay_case()` recomputes the verdict | needs a live provider — runs `mergecraft review` for real |
| Consumer | `mergecraft eval replay-bank`, the `gate_matrix` fields | `mergecraft eval bench`, the `detection` section |

A bank case cannot answer a detection question (no patch to review) and a
detection case cannot answer a gate question (no `expected_decision`) — see
`docs/dev/test-plans/eval-benchmark-b3-live.md` for why `discover_detection_cases`
silently ignores anything shaped like the other corpus rather than erroring.

### Live detection join (B3, #140)

```bash
make bench-detect
# or: mergecraft eval bench --model anthropic/claude-sonnet --json
```

Joins the keyless structural replay above with a live run against
`evals/bench/mergecraft/`: each case's patch is reviewed via the same offline
engine as `mergecraft review`, scored against its `baseline.json` with
`score_findings()`, and folded into the `detection` section of the published
result set (`evals/live_run.py`).
The structural section always populates; `detection` is `None` with a typed
`skipped_reason` — `"no live credential"` or `"no patch-bearing cases"` — when
it cannot run, never a fabricated zero. B4 seeded the detection corpus (43
patch-bearing cases); as of this writing no live provider credentials are
configured in CI, so every `bench-detect` run there reports the former.

### Seeded corpus (human-labelled, W9.0)

| Class | Count | Case ids |
|---|---:|---|
| Correctness | 3 | `issue-75-crashed-run-not-permissive`, `bench-correctness-off-by-one`, `bench-correctness-null-guard` |
| Security | 3 | `issue-75-narrative-approval`, `issue-75-untrusted-never-approves`, `bench-security-hardcoded-token` |
| Cross-file breakage | 2 | `bench-crossfile-api-signature`, `bench-crossfile-export-removed` |
| Adversarial / no-op | 2 | `bench-adversarial-clean-diff`, `bench-adversarial-minor-only` |

Ground truth is the human-labelled corpus above. LLM-as-judge scoring is a
separate measured component when live runs are enabled.

Every case added by B4 (the `evals/bench/mergecraft/` detection-corpus patches
and their `evals/cases/bench-*` bank entries) is agent-seeded/synthetic rather
than human-mined — every such row carries `provenance: agent-seeded` — and is
distinct from both the human-labelled table above and the human-provenance
tripll ReviewBench corpus described earlier in this document; caveat it
separately when publishing (B7).

Provider set defaults to **Claude + OpenAI**; estimate ~10–30 tokens per case for
a minimal live probe. Full live `mergecraft review` runs are operator-triggered, not PR CI.

### Keyless publication validation

Live case results now carry optional versioned receipts for the exact patch,
baseline, raw findings, elapsed time, and known-or-unknown provider cost. They
also carry the actual detection execution identity separately from structural
replay defaults. Older artifacts remain readable, but they cannot be published
because those facts cannot be reconstructed honestly after a run.

`mergecraft eval publish-benchmark` validates an approved two-provider campaign
manifest and two saved result sets without credentials. It verifies independent
label and judge-calibration receipts, immutable model pins, current and executed
artifact hashes, shared prompt/judge/rubric/scorer pins, raw recomputed scores,
complete case counts, and operator budget ceilings. The Make wrapper is:

```bash
make eval-publish-benchmark \
  BENCHMARK_CAMPAIGN_MANIFEST=/path/to/campaign.json \
  BENCHMARK_CAMPAIGN_RESULTS='/path/to/provider-a.json /path/to/provider-b.json' \
  BENCHMARK_CAMPAIGN_OUTPUT=evals/results
```

No approved campaign manifest or real comparative result is committed. The
agent-seeded smoke manifest remains an integrity/readiness artifact only. Model
pins are operator declarations that must exactly equal the requested slug; the
runner does not turn a floating provider alias into verified immutable identity.

## Harbor agent

Batch B ships a Harbor agent at `mergecraft.harbor.agent:MergecraftReviewAgent`.
Install the optional extra and invoke via Harbor:

```bash
uv sync --extra harbor
harbor run -d "<dataset>" --agent mergecraft.harbor.agent:MergecraftReviewAgent
```

The agent installs mergecraft with `uv tool install git+https://github.com/alexhawat/mergeCraft@<ref>`
(default ref `v0.1.0a1`, the same pin as README Example 1; override with
`MERGECRAFT_INSTALL_REF`) and runs `mergecraft diff-review --json` inside each
task environment — that is the hidden deprecated alias of `mergecraft review`
(one stderr warning per invocation).

Structured JSON output is `--json` on `mergecraft review` (the Harbor agent still
calls the hidden alias).

## See also

- [docs/eval-bank.md](../docs/eval-bank.md) — eval bank layout and CI gate semantics
- [docs/README.md](../docs/README.md) — generated documentation index
- [Landing README](../README.md) — consumer install and feature overview

## Repeated held-out detection campaign

Use the operator harness to run the same independently adjudicated,
closed-world corpus at least three times per provider. Start with the
[bounded campaign inputs and receipts](../docs/eval-methodology.md#reproducible-live-campaign).
Keep the actual held-out cases in an access-controlled snapshot until the
campaign completes. The operator should freeze case selection, prompts and
model pins before running and confirm that the held-out changes were never
used to tune the reviewer or the judge.

Each case needs a unified diff, a `baseline.json` with an explicit
`closed_world: true` and an `issues` array, and a `repo/` directory next to
the patch with the files from before the patch. An empty issues array denotes
an independently adjudicated clean case. Repository context must exclude symlinks, Git metadata,
and files named `.env` or beginning with `.env.`. Every positive issue needs
`provenance: human` and a valid path and line range. Include both defect and
clean cases. Repository context is copied into a fresh scratch directory
for each review and verified against its approved hash. The review runs with
untrusted repository settings and shell disabled. A private scratch-only
trace records reviewer dispatches with content capture and remote export
disabled. The harness requires a completed review of the full pinned patch
and one successful dispatch to the pinned model. The offline engine can retry
a transient failure. The harness rejects any resulting multi-attempt review
after execution, so it cannot prevent the retry from consuming provider quota.
Provider-internal transport retries are outside that dispatch count.

In the same directory as the campaign manifest, create a repeat protocol
with these fields.

| Field | Value |
|---|---|
| `schema_version` | `"1.0.0"` |
| `campaign_manifest` | Relative path to the approved campaign manifest |
| `campaign_sha256` | SHA-256 of the exact manifest bytes |
| `split` | `"held-out"` |
| `repetitions` | Integer, at least 3 |
| `context_sha256` | Object mapping each exact case ID to its `repo/` digest |

Compute each context digest with `make --no-print-directory -C evals detection-context-sha256
CONTEXT=/path/to/case/repo`. The approved group spend ceiling in the campaign
manifest must cover `models × cases × repetitions × per_review_cost_budget_usd`.
The harness passes the configured time, token and cost bounds to the existing
offline evaluator. Measured spend is recorded only when the evaluator reports
it. Each recorded amount, including a partial cost, counts toward the
per-review and cumulative spend checks. The cumulative known spend stops
later attempts at the approved ceiling. Reported cost can include provider or
catalog estimates. Total tokens are unavailable in the offline receipt. The
harness rejects any case configuration that scales the approved review bounds.
Use provider-side limits to cap actual charges.

From a clean checkout with the development environment installed, supply a
new results directory outside the held-out corpus.

```bash
make -C evals detection-run PROTOCOL=/path/to/repeat.json RESULTS=/path/to/results
make --no-print-directory -C evals detection-summarize \
  PROTOCOL=/path/to/repeat.json RESULTS=/path/to/results > /path/to/summary.json
```

The rescore runs without credentials. It checks both prerequisite receipts,
the approved protocol and context digests, common evaluation pins, the model
and case sets, and the recomputed scores against each run's hashed raw findings.
Each run receipt binds the protocol, context hashes, run number, and model to
its result and records the cases with one observed dispatch. A missing, partial
or failed run makes the comparison ineligible. Its recorded
case failures remain available in the individual result sets and journals.

Precision, recall and F1 pool the counts across the completed attempts for
each provider. Findings on overlapping lines in the same file are collapsed
using the eval scorer's duplicate rule with zero line slack. This is a location
surrogate for duplicate reports and can merge distinct findings at one
location. Issue matching then uses the campaign's recorded line slack. The
95% percentile intervals for precision and recall draw 2,000 resamples of
whole case IDs with replacement, carrying all attempts for each sampled case.
A resample with a zero denominator contributes no value to that metric.
Between-run sample standard deviations and every run's point estimates show
how much the reviewer varied across repetitions. Rates with no denominator
are `null`.

Clean-case false-positive rate counts only completed reviews of zero-issue
cases with any reported finding. The report also shows deduplicated findings
per clean review, median latency, and known-cost coverage. Total and median
cost are `null` if any completed review lacks a fully reported cost. The
known spend subtotal includes every recorded amount and identifies how many
reviews have only partial cost coverage. The report is written to stdout
and the harness leaves the release baseline untouched.

Run `make evals-check` from the repository root to lint, type-check, and test
the harness without provider credentials. Both `make ci-static` and
`make ci-resume` require this check.

See the [1.0 exit criteria](release-criteria.md) for the publication bar.
