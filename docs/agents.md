# Setting up mergeCraft with a coding agent

Copy-paste prompts that let a coding agent install mergeCraft, and teach it to use mergeCraft afterwards.

**Audience:** consumer (product and setup documentation)

Moved here from the landing README so the README can stay a five-minute quickstart.
The README keeps a short pointer under `#for-agents`; the machine-readable entry
points are [`AGENTS-mergecraft.md`](../AGENTS-mergecraft.md), [`llms.txt`](../llms.txt)
and the [agent skill](../skills/mergecraft/SKILL.md).

## One-line setup prompts

Open your coding agent in the repo you want reviewed, hit the copy button on
the block below, and paste. That is the whole install.

```text
Set up mergeCraft (BYOK AI PR review) in this repository.

Reference: https://github.com/alexhawat/mergeCraft/blob/main/AGENTS-mergecraft.md

Do all of this yourself, without asking me, except where step 4 says STOP:

1. Ensure `uv` is on PATH. If it is missing, install it:
     curl -LsSf https://astral.sh/uv/install.sh | sh     # macOS/Linux
     powershell -c "irm https://astral.sh/uv/install.ps1 | iex"   # Windows
   Do NOT install Python. uv downloads a compatible interpreter on its own.

2. Install the CLI:
     uv tool install mergecraft-action==0.1.0a5
     mergecraft --version
   Main-branch instructions may include unreleased behavior. Match this install
   to https://github.com/alexhawat/mergeCraft/tree/v0.1.0a5/docs before using newer features.

3. Scaffold config + workflow (non-interactive, writes no secrets):
     mergecraft init
   This creates .mergecraft/config.yaml, .github/workflows/mergecraft.yml,
   and a [learnings](glossary.md#learnings) file at .mergecraft/learnings.md.

4. STOP and hand the credential step back to me. Do not read, generate, guess,
   echo, or commit any API key, token, or .env file. Print the single command
   you want me to run. Inspect `mergecraft provider list` first; use the label
   or id configured by init (add the provider first if missing). Examples
   below assume those labels exist; use
   --scope local instead for local evaluation:
     mergecraft provider auth opencode --scope github     # OpenCode Zen (billing-backed key)
     mergecraft provider auth opencode-go --scope github  # OpenCode Go subscription
     mergecraft provider auth openai --scope github       # ChatGPT Plus/Pro/Team/Enterprise
     mergecraft provider auth anthropic --scope github    # Claude Pro/Max subscription
     mergecraft provider auth google --scope github       # Google AI Studio key
     mergecraft provider auth deepseek --scope github     # DeepSeek API key
     mergecraft provider auth minimax --scope github      # MiniMax key
     mergecraft provider auth tokenhub --scope github     # Tencent TokenHub key
     mergecraft provider auth openrouter --scope github   # OpenRouter key
     mergecraft provider auth xai --scope github          # xAI key
   Any other OpenAI-compatible endpoint also works — if I say "something else",
   read docs/authentication.md and set up the custom-provider env pair instead.
   Each command stores a GitHub Actions secret for me via `gh secret set` and
   rewrites .github/workflows/mergecraft.yml so the workflow passes that secret.

5. After I confirm the credential is stored, run `mergecraft doctor`. Its
   `workflow auth` row must be ok: if it fails, run
   `mergecraft workflow sync --apply`, or ask me to re-run the auth command.
   Fix anything else it reports that is not the credential itself. The first
   `provider auth` after `init` seeds `agents.reviewer` and `models:` — only
   edit `models:` if you want a fallback chain.

6. Commit ONLY .mergecraft/config.yaml, .mergecraft/learnings.md,
   .github/workflows/mergecraft.yml, and any `.gitignore` lines `init` added.
   Never commit secrets.
   Open a pull request titled "ci: add mergeCraft AI PR review".

7. That PR is the first review target. Tell me to watch the `mergecraft-approval`
   check on it. Re-run by pushing a commit (`synchronize`) or using
   `workflow_dispatch`. The default `mergecraft init` workflow does not listen
   for `@mergecraft review` comments.

Finally, print a short summary: provider chosen, files added, PR link, and the
exact command I still need to run (if any).
```

## Also teach your agent to *use* mergeCraft

The prompt above installs the reviewer. This one installs mergeCraft's own
knowledge into your agent, so *"review my diff"* and *"why did the mergecraft
check fail?"* work natively afterwards.

```text
Install the mergeCraft agent skill into this repo so you know its CLI,
config keys, exit codes, and failure modes.

1. Fetch the skill:
     git clone --depth 1 https://github.com/alexhawat/mergeCraft /tmp/mergecraft-src

2. Copy the generated [harness](glossary.md#harness) package for your agent from
   skills/<harness>/mergecraft/ (listed in skills/harnesses.yaml) to the path
   your agent reads. Examples:

     skills/cursor/mergecraft/     -> Cursor
     skills/grok-bot/mergecraft/   -> Grok Bot (user skill; not .agents/skills/)
     skills/opencode/mergecraft/   -> OpenCode
     skills/codex/mergecraft/      -> Codex CLI
     skills/gemini-cli/mergecraft/ -> Gemini CLI
     skills/openclaw/mergecraft/   -> OpenClaw
     skills/hermes/mergecraft/     -> Hermes Agent
     skills/copilot/mergecraft/    -> GitHub Copilot

   Almost every agent shares one install destination -- the Agent Skills
   standard path:

     .agents/skills/mergecraft/   -> Codex, Cursor, OpenCode, Gemini CLI,
                                     OpenClaw
     .claude/skills/mergecraft/   -> Claude Code (it does NOT read
                                     .agents/skills/); OpenCode reads it too
     hermes skills install        -> Hermes Agent (uses ~/.hermes/skills/)
     .github/skills/mergecraft/   -> GitHub Copilot (cloud agent, code review,
                                     CLI, VS Code agent mode)

   If your agent is none of these, copy AGENTS-mergecraft.md (as AGENTS.md) and
   llms.txt to the repo root -- every agent reads those.

3. Also copy commands/ to your agent's slash-command directory if it has one
   (Claude Code: .claude/commands/).

4. rm -rf /tmp/mergecraft-src

5. Confirm by summarising, from the skill you just installed: what the
   `mergecraft-approval` check is a function of, and what exit code 11 means.
```

<details>
<summary><b>Per-agent one-liners</b> — Claude Code, Cursor, Grok Bot, Codex, OpenCode, Gemini, Copilot, OpenClaw, Hermes</summary>

**Claude Code** — the only *packaged* install. Skill + slash commands in one step:

```text
/plugin marketplace add alexhawat/mergeCraft
/plugin install mergecraft@mergecraft
```

Then: `/mergecraft-setup` to scaffold, `/mergecraft-review` to review a local diff.

**Cursor** (chat or composer):

```text
Read https://github.com/alexhawat/mergeCraft/blob/main/AGENTS-mergecraft.md and set
mergeCraft up in this repo. Install the CLI with uv (uv fetches its own Python —
do not install Python), run `mergecraft init`, wire .mergecraft/config.yaml, and
open a PR with the workflow. Print the `mergecraft provider auth <provider> --scope github` command for
me to run myself — never touch credentials. Then copy
skills/cursor/mergecraft/ into .agents/skills/mergecraft/ so you keep the
knowledge.
```

**Grok Bot** — install the generated skill as a user skill (Settings → Plugins);
Grok Bot does not read `.agents/skills/` in consumer repos. The in-account
**mergeCraft** bot follows this same recipe:

```text
Read https://github.com/alexhawat/mergeCraft/blob/main/AGENTS-mergecraft.md and set
mergeCraft up in this repo. Install the CLI with uv (uv fetches its own Python —
do not install Python), run `mergecraft init` in the consumer repo (never in the
mergeCraft source tree), wire .mergecraft/config.yaml, and open a PR with the
workflow. Print the `mergecraft provider auth <provider> --scope github` command for me to run myself —
never touch credentials. After I confirm the secret is stored, run
`mergecraft doctor` as needed. Install the generated skill from
skills/grok-bot/mergecraft/ as a Grok Bot user skill (Settings → Plugins → Yours;
enable it for this Bot) so you keep the knowledge.
```

**Codex CLI / ChatGPT cloud agent:**

```text
Task: make this repo use mergeCraft for AI PR review.
Read https://github.com/alexhawat/mergeCraft/blob/main/AGENTS-mergecraft.md first.
Create a branch that adds .github/workflows/mergecraft.yml, pinning the action
to a full 40-character commit SHA you resolved from the repo (never an invented
tag), plus a .mergecraft/config.yaml whose `models:`
chain starts with openai/gpt-5.3-codex. Open a PR. I will add the
CODEX_AUTH_JSON secret myself — do not handle credentials.
```

**OpenCode** — mergeCraft's generic multi-provider [harness](glossary.md#harness); use it when your
model is not Anthropic/OpenAI/Google:

```text
Set up mergeCraft in this repo per
https://github.com/alexhawat/mergeCraft/blob/main/AGENTS-mergecraft.md, using the opencode
harness. Install with uv, run `mergecraft init`, then set in
.mergecraft/config.yaml:
    harness: opencode
    models: ["<my-provider>/<my-model>"]
Read docs/authentication.md and tell me exactly which
MERGECRAFT_CUSTOM_PROVIDER_BASE_URL / MERGECRAFT_CUSTOM_PROVIDER_API_KEY pair
to set as GitHub secrets for my endpoint. Do not handle the key yourself.
Copy skills/opencode/mergecraft/ into .opencode/skills/mergecraft/, then run
`mergecraft opencode install` to add the /mergecraft/* commands, the
mergecraft/reviewer subagent, the plugin, and the mcp.servers.mergecraft block.
Open a PR.
```

**Gemini CLI:**

```text
Set up mergeCraft in this repo. Follow
https://github.com/alexhawat/mergeCraft/blob/main/AGENTS-mergecraft.md. Install with uv
(do not install Python), run `mergecraft init`, set `models:` to
["google/gemini-3.1-pro-preview"] in .mergecraft/config.yaml, and open a PR
with the workflow. Print `mergecraft provider auth google --scope github` for me to run — do not
handle the API key.
```

**GitHub Copilot** (CLI, VS Code agent mode, or cloud agent) — copy the
generated package, then follow `AGENTS-mergecraft.md`. Copilot also reads
[`.github/copilot-instructions.md`](../.github/copilot-instructions.md):

```text
Read https://github.com/alexhawat/mergeCraft/blob/main/AGENTS-mergecraft.md and set
mergeCraft up in this repo. Install the CLI with uv (uv fetches its own Python —
do not install Python), run `mergecraft init`, wire .mergecraft/config.yaml, and
open a PR with the workflow. Print the `mergecraft provider auth <provider> --scope github` command for
me to run myself — never touch credentials. Then copy
skills/copilot/mergecraft/ into .github/skills/mergecraft/ so Copilot keeps the
knowledge.
```

**Any other autonomous shell agent** — OpenClaw and Hermes have generated packages
under `skills/openclaw/mergecraft/` and `skills/hermes/mergecraft/`; for agents with
no package, give them the machine-readable entry point and let them plan:

```text
Read https://raw.githubusercontent.com/alexhawat/mergeCraft/main/llms.txt —
it is a curated map of this project's docs. Then read AGENTS-mergecraft.md and
docs/authentication.md. Goal: install mergeCraft as the PR reviewer for the
repo in the current working directory.

Constraints:
  - `uv` is your only install prerequisite; it provisions Python itself. `provider auth
    openai` also needs the Codex CLI and `provider auth anthropic` needs Claude Code
    (`claude setup-token`) — escalate those to a human too.
  - `mergecraft init` is non-interactive and safe to run unattended.
  - `mergecraft provider auth * --scope github` is interactive and MUST be escalated to a human.
    Never fabricate, log, or commit a credential.
  - `mergecraft review --agent` streams versioned JSONL on stdout — use that,
    not screen-scraping, if you want to consume review results.
  - Exit codes are contractual: 0 pass, 10 findings, 11 blocking, 12 failed,
    20 inconclusive, 30 config error, 40 provider/infra, 50 timeout, 2 usage,
    1 failed verification (`audit verify`, `verify-behavior`).
    See docs/EXIT-CODES.md.

Produce a plan, execute it, then open a PR and report the escalation you need.
```

</details>

## What the agent still needs from you

| | Why | How long |
|---|---|---|
| **One provider credential** | `mergecraft provider auth … --scope github` is an interactive login (or a key paste). A well-behaved agent stops here rather than touching your secrets. | ~1 minute, once |
| **`gh` logged in** *(only for `--scope github`)* | `--scope github` (the default) stores the secret via `gh secret set`. Without `gh`, use explicit `--scope local` for local evaluation. | ~1 minute, once |

Everything else — install, scaffold, config, commit, PR — is unattended.
`mergecraft init` writes no secrets and needs no network.

## Why agents are good at this

| Surface | What it gives an agent |
|---|---|
| [`AGENTS-mergecraft.md`](../AGENTS-mergecraft.md) | Cross-vendor setup + contribution guidance for Codex, Cursor, Grok Bot, OpenCode, Gemini CLI and Copilot |
| [`skills/mergecraft/SKILL.md`](../skills/mergecraft/SKILL.md) | Agent-Skills package: setup checklist, CLI map, config keys, troubleshooting |
| [`llms.txt`](../llms.txt) · [`llms-full.txt`](../llms-full.txt) | Curated doc map, and the full corpus in one file |
| [`.claude-plugin/`](../.claude-plugin/plugin.json) · [`commands/`](../commands/) | Claude plugin manifest and `/mergecraft-setup` · `/mergecraft-review` |
| `mergecraft review --agent` | Versioned JSONL event stream (`run_started` · `phase` · `finding` · `verdict` · `run_finished`) for orchestrators |
| `mergecraft review --json out.json` | Structured findings on disk |
| [`docs/EXIT-CODES.md`](EXIT-CODES.md) | Contractual exit codes — branch on them instead of parsing text |
| `mergecraft doctor` | Self-diagnosis of git, providers, analyzers, auth, config, CI workflow credentials and MCP wiring |
| `mergecraft provider status` | Roster inspection — what CI will run, credential and wiring state, optional `--github` secret check |
| [`docs/mcp.md`](mcp.md) | **Public MCP install** — six review-only tools over stdio for Cursor, Claude Desktop, Codex, Gemini CLI, OpenCode |
| [`docs/agents-sdk.md`](agents-sdk.md) | **OpenAI Agents SDK** optional extra — embed `review_agent` as a review step (`pip install mergecraft-action[agents]`) |
| [`docs/opencode.md`](opencode.md) · [`integrations/opencode/`](../integrations/opencode/) | OpenCode integration — `/mergecraft/*` commands, read-only reviewer subagent, V2 MCP wiring, JEV + Logfire |
| `mergecraft mcp serve` | The reviewer's **in-run** MCP tool surface at `/mcp/reviewer`, Bearer-authenticated (not the public stdio profile) |

> **Reviewing *with* an agent, locally:** `mergecraft review` works offline on a
> local diff, worktree, or cloned repo — no GitHub Action required.
> See [`docs/cli.md`](cli.md).

<sub>Skill paths follow the [Agent Skills](https://agentskills.io/specification)
open standard, verified against each tool's own docs on 2026-08-21. `AGENTS.md` at the
repo root is the fallback every one of them reads.</sub>

## See also

- [Installing mergeCraft](install.md)
- [Authentication](authentication.md)
- [Public MCP install](mcp.md)
- [Troubleshooting](troubleshooting.md)
