# Plan 011: Prepare and complete the first human adjudication batch

- Status: DECIDED — ALL NINE ABSTAINED: no row has immutable code evidence; Alex recorded `abstain` for all nine on 2026-09-24 ([decision](https://github.com/alexhawat/mergeCraft/issues/780#issuecomment-5811216475)). #780 stays open; independent golden labels need a replacement batch
- Issue: [#780](https://github.com/alexhawat/mergeCraft/issues/780)
- Priority: P2; effort: M plus human review; change risk: MED.
- Planned against main `be9993367386b03f982c795ceb1d80e4a0bfcf1d`, 2026-09-22.
- Dependencies: 007. This batch alone does not complete 012, 013 or 014.

## Intent and verified current state

Nine golden cases say `source="human"` but lack recorded adjudication. Their files are descriptive metadata, not code evidence: none contains a patch, source snapshot, origin repository, commit, or PR. Alex Hawat (`alexhawat`) is the sole human adjudicator named by #780; this plan prepares reviewable material and records only decisions he actually makes.

`evals/cases/golden/golden-python-django-migration-001.json` names a destructive migration at `app/migrations/0042_drop_legacy_slug.py:1–24` but contains no patch or source snapshot. `CorpusCase` currently has title/path/lines/source. There are nine cases, eight categories (`correctness` appears twice) and eight languages. `calibration_status` verifies provenance eligibility only; it does not verify a label, create a held-out split, measure agreement, or calibrate a judge.

```
{"id":"golden-python-django-migration-001","source":"human",
 "path":"app/migrations/0042_drop_legacy_slug.py","start_line":1,"end_line":24}
```

## Scope and execution context

- `evals/cases/golden/`
- `src/mergecraft/evals/cases/golden/`
- `evals/fixtures/golden/ (new source/patch evidence)`
- `evals/adjudication/golden-batch-001.json (new review manifest)`
- `src/mergecraft/evals/human_batch.py (new strict manifest models)`
- `src/mergecraft/evals/corpora.py (only typed evidence references if required)`
- `tests/evals/test_human_batch.py (new)`
- `tests/evals/test_packaged_cases_sync.py`
- `tests/evals/test_cd_adversarial_corpora.py`
- `docs/eval-methodology.md`

Start an isolated `codex/011-human-golden-batch` branch from current main. The audit checkout was older pre-0.0.1 with an existing local config edit; preserve that edit. Run `git merge-base --is-ancestor be9993367386b03f982c795ceb1d80e4a0bfcf1d HEAD` (expected 0), then `git diff --stat be9993367386b03f982c795ceb1d80e4a0bfcf1d..HEAD -- evals/cases/golden src/mergecraft/evals/cases/golden evals/fixtures/golden evals/adjudication/golden-batch-001.json src/mergecraft/evals/human_batch.py src/mergecraft/evals/corpora.py tests/evals/test_human_batch.py tests/evals/test_packaged_cases_sync.py tests/evals/test_cd_adversarial_corpora.py docs/eval-methodology.md` and compare any changes against this plan before implementation.

Read AGENTS.md, CONTRIBUTING.md, docs/REVIEW-DOCTRINE.md and docs/eval-methodology.md. Python3.11+, uv, Make-only recurring commands, strict typed models, loguru and camelCase config aliases apply. Reuse existing schemas and evaluator machinery. Do not change consumer approval policy or trust boundaries, create new evidence/ artifacts, fabricate human records, or run paid/live work without its concrete authorization. Generated files must come from their generator. Conventional Commits ≤72-character subjects; no --no-verify.

## Commands

| Purpose | Command | Expected |
|---|---|---|
| Setup, if needed | `make setup` | exit0 in implementation checkout |
| Schema/sync tests | `make test MERGECRAFT_PYTEST_JOBS=0 PYTEST='uv run pytest -k "human_batch or adjudication or packaged_cases_sync or corpora"'` | all selected pass |
| Structural gate | `make eval-gate` | exit0; no live-quality claim |
| Wheel parity | `make test-wheel-corpus` | exit0 |
| Final implementation gate | `make ci` | exit0; never count skipped checks as passed |

Commands described as new targets are implementation deliverables, not commands claimed to exist at audit time. Replace uppercase placeholders only from the approved manifest. Human/publish prerequisites are future execution gates, not requests to interrupt this planning audit.

## Ordered steps

### 1. Prepare inspectable evidence

For each ID, locate an immutable source URL and, where available, the original repository, base/head commit SHA, and PR. A stable source link may be sufficient for Alex to review; vendoring a bounded `evals/fixtures/golden/<case-id>/task.patch` is optional and, when used, requires a SHA-256 plus appropriate attribution. Never reconstruct a plausible patch from the title. If no immutable evidence establishes the claimed path/range, set `evidence_status="missing"`; that ID is not adjudicable. Any replacement gets a new case ID and its own evidence.

Define strict Pydantic models in `human_batch.py`: the manifest has `schema_version`, `batch_id`, `adjudicator_login`, and exactly the nine #780 case IDs. Freeze `adjudicator_login="alexhawat"` in this batch file, while the reusable model validates decisions against whatever login the manifest names. Each row has `case_id`, `evidence_status: recovered|missing`, nullable source/fixture fields, and `decision: pending|confirm|correct|abstain`. Recovered rows require at least one immutable source URL or a confined fixture path/hash; missing rows require those evidence fields to be null. `confirm`/`correct` require `decided_at` and `decided_by == manifest.adjudicator_login`; `correct` requires corrected corpus fields. Forbid unknown fields and verify any local hash before rendering.

Verification: The schema/sync tests and make eval-gate pass; every review-sheet row resolves to real local fixture files and matching hashes.

### 2. Hand over one review sheet

Generate one review sheet from the manifest, ordered by case ID, with claimed title/path/range/category, immutable evidence link/hash, and `confirm|correct|abstain`. `CorpusCase` has no severity field, so do not invent one. Alex must supply every decision and correction. Record his login/timestamp only from the actual response or signed commit. No agent may fill a human confirmation.

Verification: The sheet lists exactly the nine case IDs; unanswered rows remain visibly unanswered. No new human provenance appears before Alex's decision.

### 3. Record real decisions safely

After 007 is merged and a row has recovered evidence plus an Alex decision, apply `correct` fields to the repo-root authoring row, then run `mergecraft eval adjudicate evals/cases/golden/<case-id>.json --id <case-id> --by human`. `abstain`, `missing`, and `pending` rows remain without provenance/adjudication. Run `make eval-cases-sync` from 007 and review both copies. Do not add a bulk helper that can turn pending rows into human provenance.

Verification: Each result remains an object, validates through CorpusCase, has human provenance and a typed adjudication record; both copies match. Run schema/sync and wheel gates.

### 4. Close only the actual batch

Close only if all nine rows are `confirm` or `correct`, all evidence validates, and every corpus object carries a command-produced record. Call `calibration_status([case.provenance for case in golden_cases()], required="independent")`; `eligible is True` means only that every provenance clears the independence bar. If any row is missing/abstained/pending, keep the batch incomplete and report counts. Do not claim a threshold, held-out split, human-human reliability, judge-human agreement, or trajectory quality.

Verification: make eval-gate passes; the batch report contains exactly nine independent records or explicitly remains incomplete.

## Done criteria

- [ ] Every confirmed/corrected label is backed by code evidence and an actual human response.
- [ ] All nine rows have recovered immutable evidence and actual Alex decisions before closing #780; otherwise the plan remains blocked with exact row statuses.
- [x] No judge calibration or trajectory-label completion is inferred from this batch.
- [ ] Relevant commands pass with actual results/limitations recorded.
- [ ] `git diff --check` exits0; changed paths stay within scope, plus plan status/changelog.
- [ ] Update this plan and plans/README.md; distinguish preparation complete from blocked human/operator steps.

## Stop conditions and maintenance

Unrecoverable code evidence, human abstention, or missing decisions blocks that row. Do not invent labels, historical code or adjudicator identity. Also stop/reconcile on materially drifted source, a twice-failed verification, or an out-of-scope change. Do not count skipped work as complete.

Human-human inter-rater reliability needs a second human rating an overlap sample. Judge-human Cohen's kappa uses paired judge and human decisions and is a different statistic. Nine metadata labels alone establish neither measure, a held-out evaluation, nor useful uncertainty bounds.
