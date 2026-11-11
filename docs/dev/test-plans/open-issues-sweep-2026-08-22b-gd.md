# Open issues sweep 2026-08-22b — Batch GD test plan

Maps **W7 RED** contracts for #413 to the test suite. Source plan:
`.ignorelocal/waves/open-issues-sweep-2026-08-22b-wave-plan.md`.

## D10 — README generated-skill copy prompts (#413) → W8

| Contract | Tests | Layer |
| --- | --- | --- |
| Jump-nav may keep `skills/mergecraft/SKILL.md` developer link | `tests/docs/test_readme_harness_copy_prompts.py::test_jump_nav_may_link_source_skill_developer_path` | functional |
| "Also teach your agent" must not copy source `skills/mergecraft/` | `…::test_also_teach_agent_prompt_does_not_instruct_source_skill_copy` | functional |
| "Also teach your agent" names harness package or install path | `…::test_also_teach_agent_prompt_references_generated_harness_packages` | functional |
| Per-agent one-liners must not copy source `skills/mergecraft/` | `…::test_per_agent_one_liners_do_not_instruct_source_skill_copy` | functional |
| Cursor / OpenCode one-liners name harness packages | `…::test_per_agent_skill_copy_prompts_reference_harness_packages` | functional |

## Out of scope (D10)

- Hero jump-nav `[Agent skill](skills/mergecraft/SKILL.md)` — allowed developer link.
- "Why agents are good at this" table link to `skills/mergecraft/SKILL.md` — documentation, not a copy prompt.

## xfail reconciliation

| Wave greens | Remove xfail from |
| --- | --- |
| W8 | `test_also_teach_agent_prompt_does_not_instruct_source_skill_copy`, `test_also_teach_agent_prompt_references_generated_harness_packages`, `test_per_agent_one_liners_do_not_instruct_source_skill_copy`, `test_per_agent_skill_copy_prompts_reference_harness_packages` |

## Verification commands

```bash
make lint
make typecheck
uv run pytest --collect-only -q tests/docs/test_readme_harness_copy_prompts.py
uv run pytest -q tests/docs/test_readme_harness_copy_prompts.py  # green since W8 (808763ce)
```

## W7 evidence

- README "Also teach your agent" step 2: `Copy skills/mergecraft/` (source tree).
- Cursor one-liner: `copy the repo's skills/mergecraft/ into .agents/skills/mergecraft/`.
- OpenCode one-liner: `Copy skills/mergecraft/ into .agents/skills/mergecraft/`.
- Generated harness packages exist under `skills/<harness>/mergecraft/` per `skills/harnesses.yaml`.
