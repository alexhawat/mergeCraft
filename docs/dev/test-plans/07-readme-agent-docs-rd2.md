# README / agent docs wave — RD2.1 test plan

Wave plan: `.ignorelocal/waves/07-readme-agent-docs-wave-plan.md`
Worktree: `../mergecraft-readme-agent-docs` @ `wave/readme-agent-docs`
Authoring wave: **RD2.1** (RED) · Implementation: **RD2.2** (outline-B landing + D2 hero + satellite moves)

## xfail schedule

| Wave | Test module | Marker reason | Status |
| --- | --- | --- | --- |
| **RD2.2** | `tests/docs/test_landing_readme.py` (8 tests) | `green after RD2.2` | **RED** @ RD2.1 |
| — | `tests/docs/test_landing_readme.py::test_landing_does_not_contain_full_cli_table` | *(none — RD1 pin)* | **GREEN** @ RD2.1 |
| — | `tests/docs/test_landing_readme.py::test_landing_omits_broken_demo_image` | *(none — D15 pin)* | **GREEN** @ RD2.1 |
| — | `tests/docs/test_landing_readme.py::test_no_docs_site_badge` | *(none — G1 pin)* | **GREEN** @ RD2.1 |

## Contract matrix (RD2.1 checklist)

| # | Contract | Layer | Primary test |
| --- | --- | --- | --- |
| RD2a | Outline-B headings / jump-nav for Problem·Why, How it works, Install, Features, Documentation | functional | `test_landing_has_outline_b_headings` |
| RD2b | Problem/solution region uses three cards or a markdown table | functional | `test_landing_has_problem_solution_cards` |
| RD2c | Architecture hero is a `<picture>` over committed pipeline SVGs | functional | `test_landing_has_picture_architecture_diagram` |
| RD2d | `assets/diagrams/pipeline-{light,dark}.svg` tracked and non-empty | unit | `test_diagram_svgs_exist_and_are_nonempty` |
| RD2e | `docs/diagrams/pipeline.d2` exists and names trust/verifier/findings | unit | `test_d2_source_exists` |
| RD2f | Landing omits broken demo `<img>` paths until a real capture exists | functional | `test_landing_omits_broken_demo_image` |
| RD2g | Install section uses numbered steps (Action + auth + trigger) | functional | `test_landing_has_numbered_install` |
| RD2h | Example 1 auto-review YAML stays on the landing page with a resolving Action ref | functional | `test_landing_keeps_example_one_workflow` |
| RD2i | Full CLI table stays off the landing README | functional | `test_landing_does_not_contain_full_cli_table` |
| RD2j | Moved essays land on `docs/workflows.md`, `docs/authentication.md`, `docs/install.md` | functional | `test_satellite_pages_received_moved_essays` |
| RD2k | No resurrected docs-site badge or Pages URL (G1 regression pin) | functional | `test_no_docs_site_badge` |

## RD2.1 notes

- Live tree @ RD1 Final still uses the pre-outline-B README: mermaid hero, “Get started”
  instead of “Install”, bullet-list problem copy, dangling `@v0.1.0` Example 1 pin,
  and no D2 artefacts (`docs/diagrams/pipeline.d2`, `assets/diagrams/*.svg`,
  satellite essays).
- `test_landing_does_not_contain_full_cli_table`, `test_landing_omits_broken_demo_image`, and
  `test_no_docs_site_badge` are **green pins** (no xfail) — RD1 moved the CLI table off the
  landing page, demo paths are omitted, and G1 removed the docs-site badge. The repo's
  `xpass-check` hook rejects XPASS in the allowed tree.
- `test_landing_keeps_example_one_workflow` resolves Action refs via local git
  (tag / branch / SHA) and deliberately avoids hard-coding `@v0.1.0` (D25).
- No `src/` edits in RD2.1; RD2.2 owns `README.md`, D2 source/SVGs, satellite pages,
  and `make diagrams-check`.

## Blockers for RD2.2

| Blocker | What RD2.2 must ship |
| --- | --- |
| Outline-B structure | Rewrite `README.md` to locked outline B (cards, jump-nav, Install section, docs map) |
| D2 hero | Add `docs/diagrams/pipeline.d2`, commit `assets/diagrams/pipeline-{light,dark}.svg`, wire `<picture>` |
| Satellite moves | Create `docs/workflows.md`, `docs/authentication.md`, `docs/install.md`; append manifest rows |
| Example 1 pin | Point `uses: alexhawat/mergeCraft@…` at a ref that resolves (`@pre-0.0.1`, SHA, or post-release tag per D25) |
| Makefile | Add `diagrams` / `diagrams-check` targets (D14) |

## Acceptance (RD2.1)

- 11 named tests collected with zero import errors
- `make lint` + `make typecheck` clean on touched paths
- 8 tests **XFAIL** (strict=False) + 3 green pins pending RD2.2 reconciliation
- Plan RD2.1 checkboxes flipped with commit SHA evidence
