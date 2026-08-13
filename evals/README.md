# mergeCraft evals

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

Finding-location **precision / recall / F1** and false-positives-per-run are
written only when a live run completes across ≥2 configured providers. With
missing API keys the harness records `skipped: no live credential` and omits
those metrics — do not fabricate a table in the README.

### Seeded corpus (human-labelled, W9.0)

| Class | Count | Case ids |
|---|---:|---|
| Correctness | 3 | `issue-75-crashed-run-not-permissive`, `bench-correctness-off-by-one`, `bench-correctness-null-guard` |
| Security | 3 | `issue-75-narrative-approval`, `issue-75-untrusted-never-approves`, `bench-security-hardcoded-token` |
| Cross-file breakage | 2 | `bench-crossfile-api-signature`, `bench-crossfile-export-removed` |
| Adversarial / no-op | 2 | `bench-adversarial-clean-diff`, `bench-adversarial-minor-only` |

Ground truth is the human-labelled corpus above. LLM-as-judge scoring is a
separate measured component when live runs are enabled.

Provider set defaults to **Claude + OpenAI**; estimate ~10–30 tokens per case for
a minimal live probe. Full diff-review runs are operator-triggered, not PR CI.

## Harbor agent

Batch B ships a Harbor agent at `mergecraft.harbor.agent:MergecraftReviewAgent`.
Install the optional extra and invoke via Harbor:

```bash
uv sync --extra harbor
harbor run -d "<dataset>" --agent mergecraft.harbor.agent:MergecraftReviewAgent
```

The agent installs mergecraft with `uv tool install git+https://github.com/alexhawat/mergeCraft@<ref>`
(default ref `pre-0.0.1`; override with `MERGECRAFT_INSTALL_REF`) and runs
`mergecraft diff-review --json` inside each task environment.

Structured JSON output requires Batch A (`--json` on `diff-review`) — see
[mergeCraft#30](https://github.com/alexhawat/mergeCraft/issues/30).
