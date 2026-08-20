# README / agent docs wave — RD3.1 test plan

Wave plan: `.ignorelocal/waves/07-readme-agent-docs-wave-plan.md`
Worktree: `../mergecraft-readme-agent-docs` @ `wave/readme-agent-docs`
Authoring wave: **RD3.1** (RED) · Implementation: **RD3.2** (LLM-agent install surfaces)

## xfail schedule

| Wave | Test module | Marker reason | Status |
| --- | --- | --- | --- |
| **RD3.2** | `tests/docs/test_agent_surfaces.py` (12 tests) | `green after RD3.2` | **RED** @ RD3.1 |
| — | `tests/docs/test_agent_surfaces.py::test_claude_md_still_gitignored` | *(none — D6 pin)* | **GREEN** @ RD3.1 |
| — | `tests/docs/test_agent_surfaces.py::test_cursor_tree_still_gitignored` | *(none — D7 pin)* | **GREEN** @ RD3.1 |
| — | `tests/docs/test_agent_surfaces.py::test_no_tracked_dot_claude_rules` | *(none — D7 pin)* | **GREEN** @ RD3.1 |

## Contract matrix (RD3.1 checklist)

| # | Contract | Layer | Primary test |
| --- | --- | --- | --- |
| RD3a | `AGENTS.md` teaches `mergecraft review` / `mergecraft init`; `diff-review` only as alias | functional | `test_agents_md_exists_and_teaches_review_not_diff_review_as_primary` |
| RD3b | `AGENTS.md` stops before interactive auth; never invent credentials | functional | `test_agents_md_stops_on_interactive_auth` |
| RD3c | `AGENTS.md` uses unpinned install; no dangling `@pre-0.0.1` / `@vX.Y.Z` without tag | functional | `test_agents_md_install_ref_resolves` |
| RD3d | Contributor section names `make lint` / `make test` for this repo | functional | `test_agents_md_this_repo_uses_make` |
| RD3e | Consumer skill frontmatter `name: mergecraft` + `description:` | unit | `test_skill_frontmatter` |
| RD3f | `skills-lock.json` mergecraft hash matches SKILL.md SHA-256 | unit | `test_skill_lock_hash_matches` |
| RD3g | `.claude-plugin/plugin.json` + `marketplace.json` point at skill/commands | unit | `test_plugin_manifests` |
| RD3h | Slash commands `mergecraft-setup` and `mergecraft-review` exist | functional | `test_slash_commands_exist` |
| RD3i | Copilot instructions point at `AGENTS.md` | functional | `test_copilot_instructions_point_at_agents_md` |
| RD3j | README replaces RD3 placeholder with agent section + `mergecraft init` prompt | functional | `test_readme_has_for_ai_coding_agents_section` |
| RD3k | README badges/links skill + `llms.txt` | functional | `test_readme_agent_badges` |
| RD3l | `llms.txt` maps README, AGENTS, REVIEW-CHECKS, ANALYZERS, skill | functional | `test_llms_txt_lists_required_urls` |
| RD3m | `CLAUDE.md` stays gitignored and untracked (D6) | functional | `test_claude_md_still_gitignored` |
| RD3n | `.cursor/` stays gitignored; no tracked Cursor rule (D7) | functional | `test_cursor_tree_still_gitignored` |
| RD3o | No tracked `.claude/` files (D7) | functional | `test_no_tracked_dot_claude_rules` |

## RD3.1 notes

- Live tree @ RD2 Final (`9218d1cf`) ships outline-B landing with the HTML comment
  `<!-- RD3: For AI coding agents -->` only — no `AGENTS.md`, `llms.txt`, consumer skill,
  plugin manifests, slash commands, or Copilot instructions yet.
- Three **green pins** assert D6/D7 gitignore boundaries without xfail; the repo's
  `xpass-check` hook rejects XPASS in the allowed tree.
- `test_agents_md_install_ref_resolves` reuses the D11 unpinned install string already
  on the landing page and rejects `@pre-0.0.1` / unresolved `@v…` git or Action pins.
- No `src/` edits in RD3.1; RD3.2 owns all agent-facing artefacts and the README section.

## Blockers for RD3.2

| Blocker | What RD3.2 must ship |
| --- | --- |
| `AGENTS.md` | Consumer + contributor split; review/init; stop-before-auth; unpinned install; make targets |
| Consumer skill | `skills/mergecraft/SKILL.md` with Agent-Skills frontmatter + setup checklist |
| Lockfile | Append `mergecraft` entry to `skills-lock.json` with SHA-256 hash |
| Plugin | `.claude-plugin/plugin.json` + `marketplace.json` (D8) |
| Commands | `commands/mergecraft-setup.md`, `commands/mergecraft-review.md` |
| Copilot | `.github/copilot-instructions.md` → `AGENTS.md` |
| `llms.txt` | Curated map linking README, AGENTS, REVIEW-CHECKS, ANALYZERS, skill |
| README section | Replace RD3 placeholder with prompts, skill/plugin install, badges |
| Manifest | Append rows for `AGENTS.md`, skill, `llms.txt` |

## Acceptance (RD3.1)

- 15 named tests collected with zero import errors
- `make lint` + `make typecheck` clean on touched paths
- 12 tests **XFAIL** (strict=False) + 3 green pins pending RD3.2 reconciliation
- Plan RD3.1 checkboxes flipped with commit SHA evidence
