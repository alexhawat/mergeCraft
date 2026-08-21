# README / agent docs wave — RD1.1 test plan

Wave plan: `.ignorelocal/waves/07-readme-agent-docs-wave-plan.md`
Worktree: `../mergecraft-readme-agent-docs` @ `wave/readme-agent-docs`
Authoring wave: **RD1.1** (RED) · Implementation: **RD1.2** (manifest, templates, generated pages)

## xfail schedule

| Wave | Test module | Marker reason | Status |
| --- | --- | --- | --- |
| **RD1.2** | `tests/docs/test_reference_docs.py` (all tests) | `green after RD1.2` | **RED** @ RD1.1 |
| **RD1.2** | `tests/docs/test_docs_manifest.py` (all tests) | `green after RD1.2` | **RED** @ RD1.1 |

## Contract matrix (RD1.1 checklist)

| # | Contract | Layer | Primary test |
| --- | --- | --- | --- |
| RD1a | Full action-input table lives in `docs/action-reference.md`, not README | functional | `test_action_inputs_table_lives_in_action_reference_doc` |
| RD1b | Full action-output table lives in `docs/action-reference.md`, not README | functional | `test_action_outputs_table_lives_in_action_reference_doc` |
| RD1c | Full CLI table lives in `docs/cli.md`; README has no `BEGIN:cli-commands` | functional | `test_cli_table_lives_in_cli_doc` |
| RD1d | Generator `--check` fails on `docs/cli.md` sentinel drift | integration | `test_generator_check_fails_on_cli_doc_drift` |
| RD1e | Generator `--check` fails on `docs/action-reference.md` sentinel drift | integration | `test_generator_check_fails_on_action_doc_drift` |
| RD1f | Landing README links to generated reference pages | functional | `test_readme_links_to_generated_reference_pages` |
| RD1g | `docs/manifest.yaml` lists required consumer/contributor pages | unit | `test_manifest_lists_required_pages` |
| RD1h | Manifest excludes `docs/test-plans/**` and `docs/artifacts/**` | unit | `test_manifest_lists_required_pages` |
| RD1i | `docs/README.md` links every manifest `path` | functional | `test_generated_docs_index_lists_every_manifest_row` |
| RD1j | Four `docs/_templates/*.md.tpl` files with purpose + see-also slots | unit | `test_templates_exist` |
| RD1k | `Makefile` `CI_STEPS` / `ci-static` includes `docs-check` | integration | `test_make_docs_check_is_in_ci_steps` |

## G2 carry-over (retargeted helpers)

The G2 suite in `tests/docs/test_reference_docs.py` previously parsed README sentinel
tables. RD1.1 retargets helpers to `docs/action-reference.md` / `docs/cli.md` and marks
the carry-over tests (`test_every_action_input_is_documented`, generator idempotency/drift,
auth provider parity, etc.) with the same RD1.2 xfail until the generator move lands.

Scratch-repo fixtures write `docs/cli.md` + `docs/action-reference.md` (not README
sentinels) and patch `CLI_DOC_PATH` / `ACTION_DOC_PATH` on the loaded generator module.

## RD1.1 notes

- Live tree @ `pre-0.0.1` still splices generated tables into `README.md`; none of the
  RD1.2 artefacts exist yet (`docs/manifest.yaml`, `docs/_templates/`, `docs/cli.md`,
  `docs/action-reference.md`, `docs/README.md`, `make docs-check`).
- `test_make_docs_check_is_in_ci_steps` is pinned GREEN after RD1.2 (supersedes
  `reference-docs-check` per plan D3); it xfail-skips until then like the rest of the suite.
- No `src/` edits in RD1.1; RD1.2 owns `scripts/gen_reference_docs.py`, `Makefile`, and
  the new docs tree.

## Acceptance (RD1.1)

- Named RD1.1 tests collected with zero import errors
- `make lint` + `make typecheck` clean on touched paths
- Entire suite **XFAIL** (strict=False) pending RD1.2
- Plan RD1.1 checkboxes flipped with commit SHA evidence
