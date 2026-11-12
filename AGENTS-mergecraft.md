# AGENTS-mergecraft.md — guidance for AI agents

Cross-vendor entry point for agents setting up mergeCraft in a **consumer** repo
or contributing to **this** repository. Read [`README.md`](README.md) for the
human landing page; use [`skills/mergecraft/SKILL.md`](skills/mergecraft/SKILL.md)
for a compact setup checklist and CLI reference.

## Setup mergeCraft in a consumer repo

Use this when asked to add AI PR review to another repository.

1. **Prerequisites.**
   <!-- BEGIN:requirements -->
   **Requirements:** [uv](https://docs.astral.sh/uv/) is the only prerequisite for the
   install; it downloads a compatible Python (3.11+) itself, so no system Python is
   needed. The [GitHub CLI](https://cli.github.com) (`gh auth login`) is needed only
   for `provider auth --scope github` (the default) or `--scope both`, which stores the secret
   with `gh secret set`. `mergecraft init` needs neither `gh` nor a network;
   `--scope local` needs no `gh`, but provider-specific authentication may need a network.
   Two providers need one more CLI at the credential step: the Codex CLI for `openai`
   and Claude Code for `anthropic`
   ([provider table](docs/authentication.md)).
   <!-- END:requirements -->
   If you cannot install uv, use the Docker Action path only
   ([`docs/install.md`](docs/install.md)) — no local CLI install required for CI.
2. **Install the CLI.** PyPI carries the pre-release `mergecraft-action`; the
   CLI binary is still `mergecraft`:

   ```bash
   uv tool install mergecraft-action==0.1.0a5
   mergecraft --install-completion   # optional shell completion
   ```

   Docs on `main` may describe unreleased behavior. Use the
   [matching release docs](https://github.com/alexhawat/mergeCraft/tree/v0.1.0a5/docs)
   for this install; do not assume newer CLI flags or fixes are included.

   To run an unreleased commit instead, pin the distribution to the repository:
   `uv tool install "mergecraft-action @ git+https://github.com/alexhawat/mergeCraft@<full-commit-sha>"`.

3. **Scaffold config and workflow** — in the consumer repo root:

   ```bash
   mergecraft init
   ```

4. **Authentication — STOP here.** Interactive login is required. Ask the human
   to run `mergecraft provider list` and authenticate a configured label or id.
   For local evaluation use `--scope local`; for Actions adoption, examples
   below assume these provider labels were configured by `init`:

   ```bash
   mergecraft provider auth opencode --scope github     # OpenCode Zen (billing-backed key)
   mergecraft provider auth opencode-go --scope github  # OpenCode Go subscription
   mergecraft provider auth openai --scope github       # ChatGPT Plus/Pro/Team/Enterprise
   mergecraft provider auth anthropic --scope github    # Claude Pro/Max subscription
   mergecraft provider auth google --scope github       # Google AI Studio key
   ```

   Other providers: [`docs/authentication.md`](docs/authentication.md). **Never**
   invent, paste, or commit credentials, tokens, secrets, or `.env` files. Each
   `mergecraft provider auth … --scope github` stores a GitHub Actions secret via `gh secret set` and
   rewrites `.github/workflows/mergecraft.yml` to pass it — hand that step to the human
   when interactive auth is required. Then run `mergecraft doctor`: its `workflow auth`
   row must be ok (if not, run `mergecraft workflow sync --apply`).
5. **Commit only** `.mergecraft/config.yaml`, `.mergecraft/learnings.md`,
   `.github/workflows/mergecraft.yml`, and any `.gitignore` lines `init` added
   on a new branch. Do not commit secrets.
6. **Trigger a review** — open a pull request or run the workflow via
   `workflow_dispatch`. The default `mergecraft init` workflow does **not**
   listen for `@mergecraft review` comments (comment triggers are opt-in; see
   [`docs/workflows.md`](docs/workflows.md)). Local/offline review uses
   **`mergecraft review`** (not `diff-review`, which is a deprecated alias that
   emits one stderr warning per invocation).

## Setup with Grok Bot

Use this when a Grok Bot (including the in-account **mergeCraft** bot) is
asked to add mergeCraft to another repository.

Grok Bot does **not** read `.agents/skills/` in a consumer repo. Install the
generated skill from [`skills/grok-bot/mergecraft/SKILL.md`](skills/grok-bot/mergecraft/SKILL.md)
as a Grok Bot user skill (Settings → Plugins → Yours; enable it for the Bot).

Follow the same consumer flow as other agents:

1. **`uv tool install`** the CLI (see above).
2. In the **consumer repo root** (never in the mergeCraft source tree), run
   **`mergecraft init`**.
3. **STOP for authentication.** Ask the human to run exactly one
   `mergecraft provider auth … --scope github` command. **Never** invent, paste, or commit credentials,
   tokens, secrets, or `.env` files.
4. After the human confirms the GitHub Actions secret is stored, you may run
   **`mergecraft doctor`** and **`mergecraft review`** as needed.
5. Commit only `.mergecraft/config.yaml`, `.mergecraft/learnings.md`,
   `.github/workflows/mergecraft.yml`, and any `.gitignore` lines `init` added
   on a new branch in the consumer repo.

## Working on this repo (development)

mergeCraft itself: Python **3.11+**, managed with uv, recurring commands via **Make**
only (see [`.github/CONTRIBUTING.md`](.github/CONTRIBUTING.md) and
[`docs/_standards/coding-standards.md`](docs/_standards/coding-standards.md)).

```bash
make setup      # uv sync --extra dev + pre-commit
make lint       # ruff + format + loguru-only
make typecheck  # mypy strict (make pyright runs the supplemental Pyright pass)
make test       # unit tests (not integration)
make ci         # full pre-merge gate
```

- **Source:** `src/mergecraft/` — `cli/`, `agents/`, `analyzers/`, `mcp/`, `action/`, `config/`
- **Docs:** `docs/`; review checks: [`docs/REVIEW-CHECKS.md`](docs/REVIEW-CHECKS.md)
- **Review behaviour:** read [`docs/REVIEW-DOCTRINE.md`](docs/REVIEW-DOCTRINE.md) before
  editing review logic under `modes/`, `agents/`, or `analyzers/`
- **Examples:** generated under `examples/` — edit templates in `scripts/`, not generated files
- **MCP:** `mergecraft mcp serve` (HTTP, Bearer-required per-run token on an ephemeral port;
  reviewer role at `/mcp/reviewer`) and `mergecraft mcp list` — see [`docs/cli.md`](docs/cli.md)

**Optional local overrides**

On hosts without Linux namespace isolation (`unshare`), mergeCraft refuses to run the MCP
shell tool and may refuse root outside the Action image. For local debugging only:

- `MERGECRAFT_ALLOW_UNSANDBOXED_SHELL=1` — allow the unsandboxed shell fallback when PID
  namespace isolation is unavailable.
- `MERGECRAFT_ALLOW_ROOT=1` — allow running as root outside the Action container image.
- `MERGECRAFT_PROBE_ALLOW_SUDO=1` — allow the isolation probe to retry with `sudo`
  when `CI` is unset (local capability probing only).

Do not set these in CI or production workflows.

## Rules for agents

- Do not weaken trust-tier or fail-closed security behaviour
  ([`docs/workflows.md`](docs/workflows.md), [`SECURITY.md`](SECURITY.md)).
- Conventional Commits; subject ≤ 72 characters; no `--no-verify` unless the operator allows it.
