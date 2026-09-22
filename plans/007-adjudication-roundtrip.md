# Plan 007: Make golden-case adjudication safe and round-trippable

- Status: TODO — plan ready; implementation has not started
- Issue: [#779](https://github.com/alexhawat/mergeCraft/issues/779)
- Priority: P1; effort: M; change risk: MED; confidence: HIGH.
- Planned against main `be9993367386b03f982c795ceb1d80e4a0bfcf1d`, 2026-09-22.
- Dependencies: None; blocks human batch 011.

## Intent and current state

The supported adjudication command returns success but turns a pretty-printed golden object into a list. Even unwrapping it fails `CorpusCase` because `provenance` and `adjudication` are forbidden. Human adjudication in plan 011 must not begin on this writer.

`cli/eval_cmd.py:815–817` assigns payload=rows for a bare object. `evals/corpora.py:96–111` has extra=forbid and no provenance/adjudication fields. Current loading at :151–155 prefers an existing cwd corpus, then packaged resources; the old issue's package-first statement is outdated.

```python
elif isinstance(payload, dict):
    rows = [payload]
    payload = rows
# CorpusCase:
model_config = ConfigDict(extra="forbid")
```

## Scope and conventions

Only these implementation paths, plus this plan's status and an appropriate changelog entry:
- `src/mergecraft/cli/eval_cmd.py`
- `src/mergecraft/evals/corpora.py`
- `src/mergecraft/evals/adjudication.py`
- `tests/cli/test_eval_cmd.py`
- `tests/evals/test_adjudication.py`
- `tests/evals/test_packaged_cases_sync.py`
- `scripts/sync_eval_cases.py` (new; one-way repo-root → packaged sync)
- `Makefile`
- `docs/eval-methodology.md`

Reuse AdjudicationRecord and strict Pydantic models rather than allowing arbitrary extras. Match CLI temporary-directory tests and the existing packaged byte-sync tests.

Python 3.11+, uv, src layout, strict typing, loguru and existing camelCase configuration aliases apply. Read AGENTS.md, CONTRIBUTING.md and docs/REVIEW-DOCTRINE.md. Do not change trust-tier authority, approval policy or public schemas outside the listed scope. Do not write new material under evidence/. No generated file hand-edits.

## Start and verification commands

Start a clean branch `codex/007-adjudication-roundtrip` from updated main. This plan was written in a checkout on older pre-0.0.1: do not implement there blindly or carry the user's local config edit.

1. `git merge-base --is-ancestor be9993367386b03f982c795ceb1d80e4a0bfcf1d HEAD` must exit 0.
2. `git diff --stat be9993367386b03f982c795ceb1d80e4a0bfcf1d..HEAD -- src/mergecraft/cli/eval_cmd.py src/mergecraft/evals/corpora.py src/mergecraft/evals/adjudication.py tests/cli/test_eval_cmd.py tests/evals/test_adjudication.py tests/evals/test_packaged_cases_sync.py scripts/sync_eval_cases.py Makefile docs/eval-methodology.md`; compare changed files against the excerpts before proceeding.
3. If dependencies are absent, `make setup` in the implementation checkout only.
4. Focused gate: `make test MERGECRAFT_PYTEST_JOBS=0 PYTEST='uv run pytest -k "eval_cmd or adjudication or packaged_cases_sync or corpora"'` → all selected tests pass. The Make target appends `tests`, so path arguments inside `PYTEST` are not a valid focused invocation here; the `-k` selector applies after collection.
5. Final gates: `make lint typecheck pyright`, then `make ci` → exit 0. Use `make coverage-gate` where coverage policy changes. Record actual results and skips.

## Implementation steps

### 1. Pin the behavior

Add real golden-case round-trip regressions: copy `evals/cases/golden/golden-python-django-migration-001.json` into `tmp_path`, invoke the Typer command, assert the top-level value is still a mapping, then validate it with `CorpusCase.model_validate`. Cover these existing accepted forms separately: pretty and compact bare objects, bare arrays, `{"issues": [...]}` envelopes, and JSONL with one row, blank lines, and `//` comments. Assert an unknown ID, unapproved adjudicator, self-adjudication, malformed row, and simulated replace failure leave the original bytes unchanged. Preserve envelope keys and JSONL comment/blank-line positions.

Verification: run the focused gate above. A new regression should fail for the specified behavior before implementation; after the fix all selected cases must pass. Do not accept an import/fixture error as the expected failure.

### 2. Implement the bounded change

Preserve the original container shape independently of the mutable `rows` view: for a bare object, keep `payload` bound to that object and set only `rows = [payload]`; never assign `payload = rows`. Extend the strict model with exactly `provenance: str = ""` and `adjudication: AdjudicationRecord | None = None`, importing the existing record from `mergecraft.evals.adjudication`; do not duplicate it or loosen `extra="forbid"`. Old rows must therefore load with empty provenance and no fabricated record. Before writing, decode the rendered candidate again and validate the mutated golden-object form through `CorpusCase`; retain the existing baseline issue parser for envelope/list/JSONL forms. If the shape cannot be classified without weakening validation, stop rather than accepting arbitrary extras.

Replace the final `Path.write_text` with a sibling-temp-file + `fsync` + `os.replace` helper matching `src/mergecraft/config/io.py::write_config_dict` and `src/mergecraft/cli/workflow_cmd.py::_atomic_write_text`, including mode preservation and cleanup. Only print success after the replace returns.

Verification: run the focused gate above. A new regression should fail for the specified behavior before implementation; after the fix all selected cases must pass. Do not accept an import/fixture error as the expected failure.

### 3. Implement the bounded change

Designate `evals/cases/` as the only authoring tree. Add `scripts/sync_eval_cases.py` that copies all files under the package-backed `golden/`, `mutation/`, and `skill/` subtrees from repo-root to the same relative packaged path, including newly authored cases; reject path escape/symlinks and support `--check` without writes. Do not delete packaged files automatically: report stale packaged-only paths and require an explicit reviewed deletion in both trees. Add Make targets `eval-cases-sync` and `eval-cases-sync-check`; fold only the check target into the relevant gate. Extend `test_packaged_cases_sync.py` to compare both file sets and bytes, so missing packaged copies of new authoring files fail too. `mergecraft eval adjudicate` edits exactly the path the operator passes and must never infer or rewrite its twin, an installed wheel, or an unrelated custom corpus.

Verification: run the focused gate above. A new regression should fail for the specified behavior before implementation; after the fix all selected cases must pass. Do not accept an import/fixture error as the expected failure.

### 4. Verify the complete contract

Run the focused tests, `make eval-cases-sync-check`, `make eval-gate`, `make test-wheel-corpus`, and final gates. Document the actual loader order from `_load_cases`: explicit cwd `evals/cases/<kind>` first, packaged resources second, checkout-relative fallback last. Document that corpus authors edit repo-root files, run `make eval-cases-sync`, review both copies, and only then run the check target.

Verification: run the focused gate above. A new regression should fail for the specified behavior before implementation; after the fix all selected cases must pass. Do not accept an import/fixture error as the expected failure.

## Completion criteria

- [ ] Adjudicating a real golden case preserves an object and loads through CorpusCase with a typed record.
- [ ] Existing golden rows without the new keys still validate as `provenance == ""` and `adjudication is None`.
- [ ] All accepted input shapes and policy failures preserve valid data; packaged twins remain synchronized.
- [ ] No human labels are created as part of implementation tests outside temporary fixtures.
- [ ] Focused and final gates pass; results and any environment limitation recorded.
- [ ] `git diff --check` exits 0 and `git diff --name-only` stays in scope.
- [ ] Update this status and plans/README.md; use a Conventional Commit subject ≤72 characters. Do not use --no-verify.

## Stop conditions and maintenance

Stop if an input format is ambiguous and cannot be preserved safely; reject without writing. `source="human"` is descriptive metadata and must never be converted into `provenance="human"` without a real `adjudicate_label` call. Also stop and reconcile if source excerpts have drifted, a prerequisite is incomplete, two reasonable verification attempts fail, or an out-of-scope change is necessary. Never label skipped checks as passed.

Any CorpusCase schema extension must survive source and installed-wheel loading. Keep adjudication identity independent from benchmark truth claims.
