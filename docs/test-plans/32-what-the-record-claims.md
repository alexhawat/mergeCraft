# Test plan — What the record claims (plan 32)

**Wave:** Q1 (RED suite) · branch `wave/record-claims` · base `origin/main` @ `58079e66`
**Owner:** `test-creator` · **Implementers:** Q2 (`J1`,`J2`), Q3 (`J3`,`J4`), Q4 (`J5`), Q5 (`J6`)
**Trace run:** service `mergecraft-dev` · wave.plan=what-the-record-claims · run.id=`34e605cd-ab42-49cf-bb12-553750569c4f`

This document maps every contract in the plan's Part 1 (J1–J7) and Part 2
(Q-D1…Q-D9) to the tests that pin it. RED here means *red for the right
reason*: the assertion fails against missing behaviour, never an
import/collection error.

Verification commands:

```bash
uv run pytest <paths> --collect-only -q          # collection diagnostic
uv run pytest <paths> -q -p no:randomly          # per-contract run
make lint && make typecheck                      # wave verify targets
```

## Contract → test map

| Contract | Layer | Test file / node | RED now | Greens after |
| --- | --- | --- | --- | --- |
| **J1** unprovisioned tool fails distinct from a missed finding | unit | `tests/analyzers/test_adapters_github.py::test_unprovisioned_managed_tool_skips_with_a_provisioning_reason` | no (GREEN) | already satisfied — test-only fix |
| **J1** planted-finding test captures `skipped`/`skip_reason` | functional | `tests/analyzers/test_adapters_github.py::test_adapter_catches_planted_finding[*]` | no (GREEN) | already satisfied |
| **J1** absence assertion does not pass on a skip (Q-D2) | functional | `tests/analyzers/test_adapters_github.py::test_adapter_invents_no_unplanted_findings_on_untouched_files[*]` | no (GREEN) | already satisfied |
| **J2** revision ranges / `rev:path` / regex raise zero Major findings | integration | `tests/evidence/test_trajectory_read_coverage.py::test_revision_ranges_and_regexes_are_not_changed_unread_files` | **RED** | Q2 |
| **J2** a genuinely unread modified file still raises exactly one | integration | `tests/evidence/test_trajectory_read_coverage.py::test_a_genuinely_unread_modified_file_still_raises_one_finding` | no (GREEN guard) | Q2 must not regress it |
| **J3** shipped examples export a pin equal to their `uses:` ref | unit | `tests/ci/test_checkout_credential_persistence.py::test_shipped_examples_export_the_pin_they_run[*]` | **RED** | Q3 |
| **J3** templates export `MERGECRAFT_ACTION_SHA: __ACTION_PIN__` | unit | `tests/ci/test_checkout_credential_persistence.py::test_workflow_templates_export_the_pin_placeholder[*]` | **RED** | Q3 |
| **J3** README example honours the dispatch prompt it declares | unit | `tests/ci/test_checkout_credential_persistence.py::test_readme_examples_honour_a_dispatch_prompt_they_declare` | **RED** | Q3 |
| **J4** no doc advertises `@mergecraft review` as a trigger | functional | `tests/skills/test_no_comment_trigger_claim.py::test_doc_does_not_advertise_a_comment_trigger[*]` (10 `SKILL.md` + `AGENTS.md` + `README.md` + `llms-full.txt`) | **RED** | Q3 |
| **J4** corrective/troubleshooting prose stays allowed (Q-D1, Q-D4) | unit | `tests/skills/test_no_comment_trigger_claim.py::test_the_corrective_wording_is_allowed` | no (GREEN) | Q3 must keep it |
| **J4** the pre-fix sentences are genuinely flagged | unit | `tests/skills/test_no_comment_trigger_claim.py::test_the_advertising_wording_is_flagged` | no (GREEN) | Q3 must keep it |
| **J5** budget path renders `{input} input / {output} output used (…)` | unit | `tests/review_record/test_token_summary_split_801.py::test_token_summary_from_usage_with_budget_splits_input_and_output` | **RED** | Q4 |
| **J5** no-budget fallback renders `{input} input / {output} output` | unit | `tests/review_record/test_token_summary_split_801.py::test_token_summary_from_usage_without_budget_splits_input_and_output` | **RED** | Q4 |
| **J5** deterministic record line carries the split | functional | `tests/review_record/test_token_summary_split_801.py::test_deterministic_record_line_carries_the_split` | **RED** | Q4 |
| **J5** step summary carries the split | functional | `tests/review_record/test_token_summary_split_801.py::test_step_summary_carries_the_split` | **RED** | Q4 |
| **J5** the one existing test the fix changes | unit | `tests/review_record/test_main_publish_coverage.py::test_token_summary_formats_usage_entries[rows1-…]` | **RED** (updated to the new contract) | Q4 |
| **J6** `acquire_installation_token` mint / id resolution / body / non-2xx / no-creds | unit | `tests/utils/test_token.py::test_acquire_installation_token_*` | no (GREEN) | gate for Q5; no floor here (Q-D6) |
| **J6** `_app_jwt` missing pyjwt / no creds / newline key / payload shape | unit | `tests/utils/test_token.py::test_app_jwt_*` | no (GREEN) | Q5 gate |
| **J6** `revoke_installation_token` success + failure branches | unit | `tests/utils/test_token.py::test_revoke_installation_token_*` | no (GREEN) | Q5 gate |
| **J6** `resolve_tokens` App path, fallback, `GH_TOKEN`, xrepo, `_dispose`, double-resolve | unit | `tests/utils/test_token.py::test_resolve_tokens_*`, `test_get_job_token_precedence` | no (GREEN) | Q5 gate |
| **J7** #798 capture faithfulness | — | not a test; Q5 confirms against `e19c35bf^` (Q0 item 3 already verified 8/8) | n/a | Q5 |

### Decisions applied

* **Q-D1** (never vaguer): the J1 failure message quotes `skip_reason` and names
  provisioning; the J4 check flags the advertising sentence and *allows* the
  corrective one.
* **Q-D2** (assert the distinguishing field): both J1 tests read the whole
  `AdapterRunResult`; the sibling's absence assertion is gated on a real run.
* **Q-D3** (write-side stricter than read-side): J2 pins that argument-derived
  tokens never reach `files_modified` while `files_read` keeps its permissive
  heuristic.
* **Q-D4** (verbatim wording): the J4 test's allowed form is the `pre-0.0.1`
  `037d118c` sentence; the J3 pin test is the `b72d7abe` body verbatim.
* **Q-D6** (no floor number): no test touches `scripts/check_coverage_floors.py`;
  `tests/utils/test_token.py` is behavioural only.

## Deviations from a literal port (documented)

* **J3 `test_readme_examples_honour_a_dispatch_prompt_they_declare`** is
  deliberately stricter than the `pre-0.0.1` body. There, the README example
  already declared a `prompt` input and hardcoded the value, so the guard only
  caught the hardcoding. `main`'s example declares no input at all, which makes
  the verbatim guard vacuous (it asserts nothing and passes green). The test
  therefore pins the `pre-0.0.1` contract the fix lands: *declare the prompt
  input and honour it*. The rationale is in the test docstring.
* **J4 includes `README.md`** in addition to the ten `SKILL.md` files,
  `AGENTS.md` and `llms-full.txt`. `llms-full.txt` is generated from
  `README.md` + `AGENTS.md` (`scripts/gen_llms_full.py`), so the generated
  bundle cannot be honest while its source still advertises the trigger. The
  `pre-0.0.1` correction fixes README's copy too.

## RED/GREEN counts (Q1 baseline)

`uv run pytest <the seven paths> -q -p no:randomly` → **24 failed, 49 passed**.

* J1 + J6: **31 passed** (green by design).
* J2: 1 red, 1 green guard.
* J3: 5 red.
* J4: 13 red (10 skills + 3 docs), 2 green guards + 1 parametrisation guard.
* J5: 5 red (4 new + 1 updated).

## Reconciliation log

Per-impl-wave marker removal is recorded here. At Q1 there are no `xfail`
markers: every not-yet-implemented contract is a plain failing assertion, and
every J1/J6 test is a real pass. No test is skipped or xfailed to mask a
contract.
