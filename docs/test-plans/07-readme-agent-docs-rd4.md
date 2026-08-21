# README / agent docs wave — RD4.1 test plan

Wave plan: `.ignorelocal/waves/07-readme-agent-docs-wave-plan.md`
Worktree: `../mergecraft-readme-agent-docs` @ `wave/readme-agent-docs`
Authoring wave: **RD4.1** (RED) · Implementation: **RD4.2** (docs gate + `llms-full`)

## xfail schedule

| Wave | Test module | Marker reason | Status |
| --- | --- | --- | --- |
| **RD4.2** | `tests/docs/test_docs_gate.py::test_llms_full_matches_generator` | `green after RD4.2` | **RED** @ RD4.1 |
| **RD4.2** | `…::test_llms_full_includes_agents_and_readme` | `green after RD4.2` | **RED** @ RD4.1 |
| — | `…::test_manifest_see_also_links_resolve` | *(none — links green @ RD3)* | **GREEN** @ RD4.1 |
| **RD4.2** | `…::test_satellite_readmes_have_purpose_line` | `green after RD4.2` | **RED** @ RD4.1 |
| **RD4.2** | `…::test_llms_check_and_docs_check_in_ci_steps` | `green after RD4.2` | **RED** @ RD4.1 |
| — | `…::test_install_pin_is_consistent_when_present` | *(none — D11 gate)* | **GREEN** @ RD4.1 (zero `@v…` pins) |
| — | `…::test_unpinned_install_line_is_the_documented_form` | *(none — D11 pin)* | **GREEN** @ RD4.1 |
| — | `…::test_no_eval_scores_on_landing_readme` | *(none — eval-score pin)* | **GREEN** @ RD4.1 |

## Contract matrix (RD4.1 checklist)

| # | Contract | Layer | Primary test |
| --- | --- | --- | --- |
| RD4a | Any `@v{PEP440}` pin in consumer surfaces equals `pyproject.toml` + existing git tag; zero pins passes | functional | `test_install_pin_is_consistent_when_present` |
| RD4b | README / AGENTS / skill teach unpinned `uv tool install`; no `git+…@v…` | functional | `test_unpinned_install_line_is_the_documented_form` |
| RD4c | `scripts/gen_llms_full.py --check` idempotent; drift fails with diff | integration | `test_llms_full_matches_generator` |
| RD4d | `llms-full.txt` includes README + AGENTS sections | functional | `test_llms_full_includes_agents_and_readme` |
| RD4e | Manifest paths exist; README/AGENTS/skill/`llms.txt` relative links resolve | functional | `test_manifest_see_also_links_resolve` |
| RD4f | Satellite READMEs carry template purpose + Audience in first 20 lines | functional | `test_satellite_readmes_have_purpose_line` |
| RD4g | `llms-check` wired into Makefile / `docs-check` / `CI_STEPS` | integration | `test_llms_check_and_docs_check_in_ci_steps` |
| RD4h | Landing README omits published precision/recall/F1 benchmark numbers | functional | `test_no_eval_scores_on_landing_readme` |

## RD4.1 notes

- Precondition @ `fb8c4c9b`: `AGENTS.md`, skill, `llms.txt`, and README agent section exist (RD3 Final).
- `git tag --list` is empty — pin gate skips tag-existence half with an explicit message when
  that branch would otherwise run; zero `@v…` matches keeps (a) trivially green (D11).
- `test_manifest_see_also_links_resolve` resolves markdown targets from each source file's
  directory (skill uses `../../…` paths).
- Four tests xfail `strict=False` pending RD4.2; four green pins (D11 install/pin, eval scores,
  manifest/link resolution) assert posture already met @ RD3 Final.

## Blockers for RD4.2

| Blocker | What RD4.2 must ship |
| --- | --- |
| `scripts/gen_llms_full.py` | Python generator with `--check`; `===== FILE: … =====` headers |
| `llms-full.txt` | Generated bundle of README, AGENTS, REVIEW-CHECKS, ANALYZERS, etc. |
| Makefile | `llms` / `llms-check` targets folded into `docs` / `docs-check` |
| Pin helper | Extend `scripts/gen_docs.py` or sibling to centralize version/tag checking |
| Template headers | Purpose + Audience on `CONTRIBUTING.md`, `evals/README.md`, brand/assets READMEs |
| `docs/manifest.yaml` | Append `llms-full.txt` row (`generator: llms-full`) |
| `docs/assets/README.md` | Restate demo capture path (`assets/demo.mp4` + GIF fallback) |
| CHANGELOG | Added entry for `llms-full.txt` + docs pin/link gate |

## Acceptance (RD4.1)

- 8 named tests collected with zero import errors
- `make lint` + `make typecheck` clean on touched paths
- 4 tests **XFAIL** (strict=False) + 4 green pins (3 D11/eval + link gate) pending RD4.2 reconciliation
- Plan RD4.1 checkboxes flipped with commit SHA evidence (2026-08-20 ✅: `9589985e` — 4 passed, 4 xfailed)
