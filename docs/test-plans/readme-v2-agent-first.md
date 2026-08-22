# README v2 agent-first — test plan

Maps **PR RV1** RED contracts to the test suite authored for RV2–RV6 implementation waves.
Source plan: `.ignorelocal/waves/08-readme-v2-agent-first-wave-plan.md`.

## RV1.1 — retitle guard (V1, D2) → RV6

| Contract | Tests | Layer |
| --- | --- | --- |
| `## For LLM / Agents` title + `mergecraft init` in region | `tests/docs/test_agent_surfaces.py::test_readme_has_agent_section` | functional |
| Agent H2 is first content section | `…::test_agent_section_is_first_section` | functional |
| `id="for-agents"` + `llms.txt#for-agents` | `…::test_agent_section_anchor_survives` | integration |
| Fenced prompts (copy button) | `…::test_agent_prompts_are_fenced_not_quoted` | functional |

## RV1.2 — glossary → RV2

| Contract | Tests | Layer |
| --- | --- | --- |
| `docs/glossary.md` + manifest row | `tests/docs/test_glossary.py::test_glossary_exists_and_is_manifested` | integration |
| Required term anchors | `…::test_glossary_defines_required_terms` | unit |
| First-use links on landing | `…::test_landing_jargon_is_linked_on_first_use` | functional |
| No `<abbr title>` (D5) | `…::test_no_abbr_title_tooltips` | functional |

## RV1.3 — agent packaging → RV3

| Contract | Tests | Layer |
| --- | --- | --- |
| Harness manifest coverage | `tests/docs/test_agent_packages.py::test_every_declared_harness_has_a_package_or_fallback` | integration |
| Generator `--check` | `…::test_packages_match_generator` | integration |
| Absolute URLs resolve (D9) | `…::test_generated_packages_have_no_broken_relative_links` | unit |
| Unverified → `fallback: agents-md` (D3) | `…::test_unverified_formats_are_marked` | unit |
| README paths ⊆ manifest | `…::test_readme_paths_match_harness_manifest` | functional |
| `agent-packages-check` in `CI_STEPS` | `…::test_make_agent_packages_check_in_ci_steps` | integration |

## RV1.4 — auth table → RV4

| Contract | Tests | Layer |
| --- | --- | --- |
| Recommended model column | `tests/docs/test_auth_reference.py::test_auth_table_has_recommended_model_column` | functional |
| Live slugs only | `…::test_recommended_slugs_are_real` | integration |
| Custom OpenAI-compatible row | `…::test_custom_openai_compatible_row_present` | functional |
| Auth subcommand parity | `…::test_every_auth_subcommand_has_a_row` | integration |

## RV1.5 — CLI examples → RV5

| Contract | Tests | Layer |
| --- | --- | --- |
| Complete example trees (D11) | `tests/docs/test_cli_examples.py::test_every_example_tree_is_complete` | E2E |
| Offline `run.sh` (D12) | `…::test_run_sh_is_offline` | functional |
| Expected fixtures | `…::test_expected_output_fixtures_match` | E2E |
| Manifest exclusion (D10) | `…::test_examples_are_not_manifested` | integration |
| Landing CLI section (A7) | `…::test_landing_has_cli_section` | functional |

## RV1.6 — landing swap, pin, init → RV6

| Contract | Tests | Layer |
| --- | --- | --- |
| GitHub Action section title (A4) | `tests/docs/test_landing_readme.py::test_landing_action_section_is_named_for_github_action` | functional |
| Release tag pin (A6/D7) | `…::test_landing_pins_a_release_tag` | functional |
| No SHA pin caveat | `…::test_landing_has_no_sha_pin_caveat` | functional |
| Forbid `readme_test.md` in README (D16) | `tests/docs/test_distribution_checklist.py::test_readme_drops_ideal_and_todo_asset_comments` | functional |
| Published Action ref in init | `tests/cli/test_init_cmd.py::test_scaffolded_workflow_references_published_action` | integration |
| `pull_request` trigger | `…::test_scaffolded_workflow_triggers_on_pull_request` | integration |
| `models:` list config | `…::test_scaffolded_config_uses_models_list` | integration |
| Pin consistency | `…::test_scaffolded_workflow_pin_matches_defaults_yaml` | integration |

## xfail reconciliation

| Wave greens | Remove xfail from |
| --- | --- |
| RV2 | `test_glossary.py` (except `test_no_abbr_title_tooltips` if still applicable) |
| RV3 | `test_agent_packages.py` |
| RV4 | `test_auth_reference.py` |
| RV5 | `test_cli_examples.py` |
| RV6 | `test_agent_surfaces.py` (agent section), `test_landing_readme.py` (RV1.6), `test_init_cmd.py` |

## Verification commands

```bash
make lint
make typecheck
uv run pytest --collect-only -q tests/docs/test_glossary.py tests/docs/test_agent_packages.py \
  tests/docs/test_auth_reference.py tests/docs/test_cli_examples.py \
  tests/docs/test_agent_surfaces.py tests/docs/test_landing_readme.py \
  tests/docs/test_distribution_checklist.py tests/cli/test_init_cmd.py
```

Expected: collection succeeds; named RV1 contracts are **RED** (`xfail` or fail) until the matching impl wave lands.
