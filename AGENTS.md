# AGENTS.md — guidance for AI agents

Cross-vendor entry point for agents setting up mergeCraft in a **consumer** repo
or contributing to **this** repository. Read [`README.md`](README.md) for the
human landing page; use [`skills/mergecraft/SKILL.md`](skills/mergecraft/SKILL.md)
for a compact setup checklist and CLI reference.

## Setup mergeCraft in a consumer repo

Use this when asked to add AI PR review to another repository.

1. **Prerequisites** — Python **3.11+** ([`docs/dev/python-version-floor.md`](docs/dev/python-version-floor.md)),
   [uv](https://docs.astral.sh/uv/), and an authenticated [`gh`](https://cli.github.com)
   CLI. If Python 3.11+ is unavailable locally, use the Docker Action path only
   ([`docs/install.md`](docs/install.md)) — no local CLI install required for CI.
2. **Install the CLI** (PyPI is not published yet):

   ```bash
   uv tool install "merge-craft @ git+https://github.com/alexhawat/mergeCraft"
   mergecraft --install-completion   # optional shell completion
   ```

3. **Scaffold config and workflow** — in the consumer repo root:

   ```bash
   mergecraft init
   ```

4. **Authentication — STOP here.** Interactive login is required. Ask the human
   to run exactly one of:

   ```bash
   mergecraft auth claude   # Claude Pro/Max subscription
   mergecraft auth codex    # ChatGPT Plus/Pro/Team/Enterprise
   ```

   Other providers: [`docs/authentication.md`](docs/authentication.md). **Never**
   invent, paste, or commit credentials, tokens, secrets, or `.env` files. Each
   `mergecraft auth …` stores a GitHub Actions secret via `gh secret set` — hand
   that step to the human when interactive auth is required.
5. **Commit only** `.mergecraft/config.yaml` and `.github/workflows/mergecraft.yml`
   on a new branch. Do not commit secrets.
6. **Trigger a review** — open a pull request, comment `@mergecraft review`, or
   run the workflow via `workflow_dispatch`. Local/offline review uses
   **`mergecraft review`** (not `diff-review`, which is a deprecated alias that
   emits one stderr warning per invocation).

## Working on this repo (development)

mergeCraft itself: Python **3.11+**, managed with uv, recurring commands via **Make**
only (see [`CONTRIBUTING.md`](CONTRIBUTING.md) and
[`docs/_standards/coding-standards.md`](docs/_standards/coding-standards.md)).

```bash
make setup      # uv sync --extra dev + pre-commit
make lint       # ruff + format + loguru-only
make typecheck  # mypy strict + pyright pass
make test       # unit tests (not integration)
make ci         # full pre-merge gate
```

- **Source:** `src/mergecraft/` — `cli/`, `agents/`, `analyzers/`, `mcp/`, `action/`, `config/`
- **Docs:** `docs/`; review checks: [`REVIEW-CHECKS.md`](REVIEW-CHECKS.md)
- **Review behaviour:** read [`docs/REVIEW-DOCTRINE.md`](docs/REVIEW-DOCTRINE.md) before
  editing review logic under `modes/`, `agents/`, or `analyzers/`
- **Examples:** generated under `examples/` — edit templates in `scripts/`, not generated files
- **MCP:** `mergecraft mcp serve` (HTTP, Bearer-required per-run token on an ephemeral port;
  reviewer role at `/mcp/reviewer`) and `mergecraft mcp list` — see [`docs/cli.md`](docs/cli.md)

### Local development overrides

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
- Do not add entries to `evidence/` (slated for deletion).
- Conventional Commits; subject ≤ 72 characters; no `--no-verify` unless the operator allows it.
