# OpenCode integration

OpenCode is mergeCraft's generic multi-provider harness: set `harness: opencode`
in `.mergecraft/config.yaml` and mergeCraft runs the review on any
OpenAI-compatible model. This page covers the other direction — running
mergeCraft from inside OpenCode, with commands, a read-only reviewer subagent,
and the public MCP server.

Sources live in [`integrations/opencode/`](../integrations/opencode). Install
by copying from there; `mergecraft opencode install` automates it.

## What you can do

| Want | Use |
|------|-----|
| Review the working tree with no extra provider spend | `/mergecraft/review` (native reviewer) |
| Full engine: analyzers, JEV screen, verifier, evidence | `/mergecraft/review-deep` |
| Machine-readable findings | `/mergecraft/review-json`, or `/mergecraft/review-cli` |
| Review only staged changes | `/mergecraft/review-staged` |
| Review a pull request | `/mergecraft/review-pr <n>` |
| Security-only pass | `/mergecraft/review-security` |
| Cheap deterministic pass | `/mergecraft/review-quick` |
| A third-party gateway model | `/mergecraft/review-thirdparty <provider/model>` |
| Inspect the prompt without a model call | `/mergecraft/review-dry` |
| Fix findings and re-review | `/mergecraft/apply-findings` |
| Set up / diagnose | `/mergecraft/setup`, `/mergecraft/doctor` |
| MCP, JEV, Logfire | `/mergecraft/mcp`, `/mergecraft/jev`, `/mergecraft/logfire` |

## Engines

The engine decides who reviews and how much evidence is gathered.

| Engine | Runs | Needs | Spend |
|--------|------|-------|-------|
| `native` (default) | The `mergecraft/reviewer` subagent reads the diff and grades it | OpenCode only | Your OpenCode model |
| `cli` | `mergecraft review --agent`, JSONL findings | CLI | mergecraft provider |
| `deep` | analyzers → JEV screen → reviewer → verifier → evidence | CLI + provider | mergecraft provider |
| `mcp` | public MCP `review_change` → `inspect_finding` | CLI + MCP | mergecraft provider |
| `quick` | deterministic analyzers only | CLI | none |
| `thirdparty` | pins a gateway on the `opencode` harness, then `deep` | CLI + endpoint | gateway |

`native` is the default because it is free of mergecraft provider cost and works
offline. Reach for `deep` when a change is high-stakes.

The plugin (companion change) makes the default configurable with the `engine`
plugin option, so `/mergecraft/review` can be `cli` or `deep` without editing
commands.

## Install

```bash
git clone --depth 1 https://github.com/alexhawat/mergeCraft /tmp/mergecraft-src
mkdir -p .opencode
cp -R /tmp/mergecraft-src/integrations/opencode/commands .opencode/
cp -R /tmp/mergecraft-src/integrations/opencode/agents   .opencode/
mkdir -p .opencode/skills
cp -R /tmp/mergecraft-src/skills/opencode/mergecraft .opencode/skills/mergecraft
rm -rf /tmp/mergecraft-src
```

Install the CLI if you want the `cli`, `deep`, `quick`, or `mcp` engines:

```bash
uv tool install "merge-craft @ git+https://github.com/alexhawat/mergeCraft"
mergecraft init
```

## Agents

Two subagents ship:

- **`mergecraft/reviewer`** — read-only (`edit` and `shell` denied). Grades the
  diff against the connected MCP policy, `REVIEW-CHECKS.md` when present, then a
  built-in three-axis rubric. Emits findings and exactly one verdict.
- **`mergecraft/fixer`** — the only writer. Applies findings, then re-reviews
  with `mergecraft review --agent` and stops on the exit code. mergeCraft stays
  review-only; the fix loop lives on the OpenCode side.

## MCP

OpenCode V2 nests servers under `mcp.servers` and uses `disabled` (not `enabled`):

```jsonc
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "servers": {
      "mergecraft": {
        "type": "local",
        "command": ["mergecraft", "mcp", "serve", "--role", "public", "--transport", "stdio"]
      }
    }
  }
}
```

```bash
opencode mcp add mergecraft -- mergecraft mcp serve --role public --transport stdio
opencode mcp list
```

Six review-only tools: `review_change`, `get_review`, `inspect_finding`,
`explain_finding`, `get_capabilities`, `get_policy`. None commits, pushes, or
edits the reviewed tree. The Bearer-authenticated runtime harness at
`/mcp/reviewer` is a different profile and is not for OpenCode.

## JEV

JEV (TypeSafe System One) is the pre-LLM screening gate in
`src/mergecraft/jev/`. It ranks and annotates units before the generative
reviewer.

```bash
mergecraft jev enable     # writes jev.enabled: true, prompts for TYPESAFE_API_KEY
mergecraft jev status
mergecraft jev set <key> <value>
mergecraft jev disable
```

**Honest scope:** the gate is a shadow ranker today. `predict_jev_action` in
`jev/policy.py` returns `enforced=False` unconditionally, so `enforce` does not
enforce and nothing is withheld from the reviewer. Do not configure a repository
on the assumption that JEV blocks a merge. See
[`jev-gate-patterns.md`](jev-gate-patterns.md).

The companion plugin registers the `typsafe` provider in OpenCode so JEV is
available as a model there too.

## Logfire

mergeCraft's tracing covers the `cli`, `deep`, and `mcp` engines.

```bash
mergecraft auth logfire                                  # local .env
mergecraft tracing logfire wire-workflow --region us     # CI, patch the workflow
mergecraft config tracing                                # resolved sinks, token redacted
```

OpenCode V2 has no documented OpenTelemetry export of its own. To get native
reviews into Logfire, the companion plugin emits an OTLP span per native review
when `MERGECRAFT_LOGFIRE_TOKEN` (or `LOGFIRE_TOKEN`) is present, using
`MERGECRAFT_TRACING_REGION` to pick the `us` or `eu` endpoint. Native and `deep`
reviews then share one Logfire project.

## Plugin (companion change)

The plugin under `integrations/opencode/plugins/mergecraft/` uses the OpenCode V2
`Plugin.define` entrypoint and will:

- **Register** the public MCP server (`ctx.mcp.transform`), the commands
  (`ctx.command.transform`), the reviewer/fixer agents (`ctx.agent.transform`),
  the skill (`ctx.skill.transform`), and `REVIEW-CHECKS.md` /
  `REVIEW-DOCTRINE.md` as a reference (`ctx.reference.transform`).
- **Hook** `session.prompt` (review-intent detection and secret redaction),
  `session.context` (inject doctrine for the reviewer; drop write tools;
  low temperature), `tool.execute.before` / `tool.execute.after` (observe edits,
  run `mergecraft analyzers detect`), `permission.evaluate` (enforce review-only
  for the reviewer agent), `shell.create.before` (inject `MERGECRAFT_*` env, cap
  timeouts), and the event stream (offer a review when a session goes idle with a
  dirty tree).
- **Hold V1 compatibility** with a `server()` export for mixed fleets.

It never weakens a configured `deny` and never commits, pushes, or edits on
mergeCraft's behalf.

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `/mergecraft/review-deep` says the CLI is missing | mergeCraft not installed | `uv tool install "merge-craft @ git+https://github.com/alexhawat/mergeCraft"` |
| MCP tools absent | server not configured or not connected | `opencode mcp list`; add the `mcp.servers.mergecraft` block |
| Broken MCP config | V1 shape (`mcp.mergecraft`, `enabled`) | use `mcp.servers.mergecraft` and `disabled` |
| Reviewer reports no diff | nothing changed | check `git status`; pass a ref to `/mergecraft/review` |
| JEV still not blocking | it never does — shadow gate | read the section above |

## See also

- [`docs/mcp.md`](mcp.md) — public MCP install for every host
- [`docs/agent-loop.md`](agent-loop.md) — the change → review → decide loop
- [`integrations/opencode/README.md`](../integrations/opencode/README.md) — asset index
