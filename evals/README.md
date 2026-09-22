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
