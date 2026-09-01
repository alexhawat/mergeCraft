# Per-harness Agent Skills packages

mergeCraft ships one **source** skill at [`mergecraft/SKILL.md`](mergecraft/SKILL.md).
Every harness-specific copy under `skills/<harness-id>/` is **generated** — do not edit
those files by hand.

Regenerate after changing the source skill or `harnesses.yaml`:

```bash
make agent-packages
```

CI enforces drift with `make agent-packages-check`, which runs
`scripts/gen_agent_packages.py --check` and `agentskills validate` (from the
[`skills-ref`](https://github.com/agentskills/agentskills/tree/main/skills-ref) package)
over each generated directory.

## Install matrix (G2 verified 2026-08-21)

| Path / command | Harnesses | Notes |
| --- | --- | --- |
| `.agents/skills/mergecraft/` | Codex, Cursor, OpenCode, Gemini CLI, **OpenClaw** | Cross-vendor Agent Skills path. Gemini CLI prefers it over `.gemini/skills/`. |
| `.claude/skills/mergecraft/` | Claude Code, OpenCode | Claude Code does **not** read `.agents/skills/` ([anthropics/claude-code#31005](https://github.com/anthropics/claude-code/issues/31005)). |
| `hermes skills install` | Hermes | Hermes uses `~/.hermes/skills/` or a category-nested project `skills/` tree. |

**OpenClaw** reads `.agents/skills/` only — it does **not** read `.claude/skills/`.
Copying to `.claude/skills/` is a common mistake and will not work.

**Hermes** is a [Nous Research](https://nousresearch.com/) agent. mergeCraft already
ships a Nous provider (`mergecraft auth nous`, `nous/deepseek/deepseek-v4-flash`), so a
Hermes user can run mergeCraft entirely on Nous credentials when configured. The Hermes
package declares `required_environment_variables` in frontmatter so Hermes prompts for
provider credentials securely — never paste secrets into the skill body.

## Primary sources

| Harness | Source | Verified |
| --- | --- | --- |
| Codex | https://learn.chatgpt.com/docs/build-skills | 2026-08-21 |
| Cursor | https://cursor.com/docs/skills | 2026-08-21 |
| Grok Bot | https://docs.x.ai/grok-bot/skills-routines-and-automations | 2026-09-01 |
| OpenCode | https://opencode.ai/docs/skills | 2026-08-21 |
| Gemini CLI | https://geminicli.com/docs/cli/skills | 2026-08-21 |
| OpenClaw | https://docs.openclaw.ai/tools/skills | 2026-08-21 |
| Hermes | https://hermes-agent.nousresearch.com/docs/developer-guide/creating-skills | 2026-08-21 |
| Claude Code | https://code.claude.com/docs/en/skills | 2026-08-21 |

All targets implement the [Agent Skills](https://agentskills.io/specification) open
standard (`name` + `description` frontmatter). Future harnesses must cite a primary source
with a retrieval date here, or ship the `AGENTS.md` + `llms.txt` fallback instead of
inventing a path.
