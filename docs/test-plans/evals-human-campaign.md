# Human and operator half of the evals program — test plan (HL1)

Wave plan: `.ignorelocal/waves/47-evals-human-campaign-wave-plan.md`
Worktree: `mc-human` @ `wave/evals-human-campaign`
Authoring wave: **test-creator** (HL1). Implementation: **HL2** (batch-1 decisions),
**HL3**, **HL4**, **HL5** (separate PRs). Final gate: **HL7**.

HL1 is tests-only and lands before any human decision exists. It replaces the
two preparation-state pins in `tests/evals/test_human_batch.py` with invariants
that hold *before, during and after* Alex's decisions, and adds the missing
manifest ↔ corpus agreement guard. Nothing here is `xfail`: every invariant is
green on today's all-`pending` data.

## Contract matrix

| Contract | Layer | Scenario class | Primary test(s) |
| --- | --- | --- | --- |
| **HL1.1** manifest names exactly the nine frozen IDs, `adjudicator_login == "alexhawat"`, and every non-`pending` row carries `decided_by == adjudicator_login` + `decided_at` | unit | happy (all-pending today); future confirmed/corrected rows | `tests/evals/test_human_batch.py::test_manifest_names_the_nine_and_attributes_every_decision` |
| **HL1.2** agreement guard, per case: corpus `provenance == "human"` + independent human `adjudication` **iff** the row is `confirm`/`correct` with `evidence_status == "recovered"`; `pending`/`abstain`/`missing` rows carry neither field | unit | happy (pending rows → neither field); future recovered confirm/correct | `…::test_manifest_row_and_authoring_case_agree_on_human_provenance[<case-id>]` (9 params) |
| **HL1.2** agreement guard over the whole batch in manifest order | integration | happy | `…::test_manifest_and_authoring_corpus_agree_across_the_whole_batch` |
| **HL1.3** a `correct` row's corpus object equals its `corrected_fields` for every supplied field | unit | happy (vacuous while no row is `correct`); future corrected rows | `…::test_correct_rows_match_their_corrected_corpus_fields` |
| **HL1.4** rendered sheet shows `UNANSWERED` for exactly the `pending` rows and `<decision> by <login>` for the rest, still with no severity column | functional | happy | `…::test_review_sheet_marks_only_pending_rows_unanswered` |
| **HL1.5** RED case: adjudicating a `pending` case with the real CLI adds corpus provenance the manifest never authorised; the guard fails and names the case ID | functional / E2E | error + regression | `…::test_adjudicating_a_pending_case_breaks_the_agreement_guard` |

## Layer coverage

- **Unit.** `_assert_row_and_corpus_agree` is exercised per case through the
  nine-case parametrization; `_row_claims_human_provenance` is the single
  predicate both branches key on. The row model's own validators stay covered by
  the twelve pre-existing tests below.
- **Integration.** `_assert_manifest_corpus_agreement` reads the committed
  manifest (`load_human_batch`) and every authoring object under
  `evals/cases/golden/`, so a manifest row and the corpus object it authorises
  are checked together. It is the seam nothing else in the repo connects.
- **Functional / E2E.** HL1.5 drives `mergecraft eval adjudicate` through
  `typer.testing.CliRunner` against a throwaway `evals/cases/golden/` copy, the
  same path `tests/evals/test_adjudication.py` uses for the supported writer.

## The RED case (HL1.5)

The mutation is the one the plan exists to forbid: a `pending` manifest row whose
authoring case has been adjudicated anyway.

1. The nine authoring objects are copied into `tmp_path/evals/cases/golden/`.
2. The guard is asserted **green on the untouched copy** first, so a later
   failure is the mutation's doing and not the throwaway layout's.
3. `CliRunner` runs `eval adjudicate <copy> --id golden-python-django-migration-001 --by human`;
   it exits `0` and prints `provenance human (tier independent)`.
4. The test asserts the **distinguishing field**, not mere absence:
   `payload["provenance"] == "human"` and
   `payload["adjudication"]["adjudicated_by"] == "human"`, while the manifest row
   is still `decision == "pending"`.
5. `_assert_manifest_corpus_agreement` must raise `AssertionError`, and the
   message must contain the case ID and the `provenance` field.

The exact assertion that fires:

```text
golden-python-django-migration-001: the authoring case carries provenance='human'
and adjudication=AdjudicationRecord(adjudicated_by='human', …, independence='independent', …),
but its manifest row is decision='pending' with evidence_status='missing'
```

## Kept unchanged

`test_manifest_forbids_unknown_fields`, `test_manifest_requires_exactly_the_frozen_nine_case_ids`,
`test_missing_evidence_cannot_carry_a_source_or_fixture`,
`test_recovered_evidence_requires_an_immutable_source_or_fixture`,
`test_mutable_source_url_is_rejected`,
`test_pending_decision_cannot_prepopulate_human_identity`,
`test_abstain_requires_actual_human_identity_but_not_recovered_evidence`,
`test_confirm_requires_recovered_evidence_and_matching_human_identity`,
`test_correct_requires_at_least_one_corrected_corpus_field`,
`test_fixture_path_is_confined_to_its_case_directory`,
`test_fixture_hash_is_verified_before_rendering`, and
`test_corrected_fields_are_merged_through_strict_corpus_case_validation`.

Packaged-twin equality is deliberately **not** asserted here; it stays with
`tests/evals/test_packaged_cases_sync.py` and `make eval-cases-sync-check`.

## xfail reconciliation

None. HL1 uses no `xfail` markers, so there is nothing to remove after HL2.
After HL2 records decisions, the guard in HL1.2 and the `correct` check in HL1.3
are the tests that start doing real work; they must stay green as provenance
lands.
