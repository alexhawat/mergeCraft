# mergeCraft CLI review — 2026-11-03

Scope: the `mergecraft` command-line interface (`src/mergecraft/cli/`, 70 modules, ~20,450
lines) at commit `3000d1c` on `main`, package version `0.1.0a4`. Method: full command-tree
dump from the live Typer app, offline smoke run of every leaf command, source reading of the
overlapping command families, docs coverage audit, and the project's open issues.
Companion: [`plans/cli-test-plan.md`](cli-test-plan.md) is the live-provider test campaign.

## 1. Answers to the direct questions

### When was the CLI last updated?

Today. The last commit touching `src/mergecraft/cli/` is `4e0183e` on 2026-11-03
("fix(config): restore timeout floats and the fail-closed setup path"), part of the
pydantic-settings wave merged as PR #1127. The `cli/` package has had commits on 2026-11-03,
2026-11-01, 2026-10-31, 2026-10-27, and most days in mid-October. It is actively maintained,
not dormant. The last release tag/version bump is `0.1.0a4` (published to PyPI as
`mergecraft-action` on 2026-10-27).

### Do the CLI and the CI (GitHub Action) share code?

Yes. They are one Python package, one console script, and one Typer application. They
differ only in the *driver* that sits on top of a shared review engine.

```
GitHub Action:  runner → docker image → /entrypoint.sh gha → `mergecraft gha` (Typer)
                → cli/gha_cmd._run_main → mergecraft.main.main()   [entry="action"]
                → ReviewEngine → agents/* + mcp/server + analyzers + modes
                → scm/github: post review, status checks, SARIF upload, $GITHUB_OUTPUT

Local CLI:      `mergecraft review` (same Typer app) → cli/diff_review_cmd.run
                → offline_review.run_offline_diff_review()            [entry="cli"]
                → ReviewEngine → review/offline_agent (agents/* + mcp/server) + analyzers + modes
                → stdout / --json / --agent JSONL / evidence packet / local cache
```

Evidence: `action.yml` runs the Docker image with `args: ["gha"]`; `docker-entrypoint.sh`
executes `mergecraft gha`; `pyproject.toml` declares `mergecraft = "mergecraft.cli.app:main"`
as the only script; `cli/app.py` registers `gha_cmd.app`; `cli/gha_cmd.py` calls
`mergecraft.main.main()`. The review core is shared: `review/engine.py` ("ReviewRun: Protocol
implemented by Action and offline drivers"), `agents/*` (claude, codex, gemini, opencode
harnesses), `mcp/server`, `modes/*`, `analyzers/*`, `findings`/`evidence`, `config/*`,
`utils/agent_resolve` (model chain) and `main_outcome` are imported by both drivers.

What is Action-only: `main.py` itself, `action/inputs.py` (the `with:` inputs), `scm/github`
publishing, `utils/status_checks`, `utils/code_scanning`, `ci/sarif_ingest`, GitHub App
token handling (`gha token`). What is CLI-only: `offline_review.py`,
`review/offline_agent.py`, `review/offline_stages.py`, `cli/agent_protocol.py` (the `--agent`
JSONL stream), and `ci/local_evidence.py` (`--with-coverage`, `--with-mutation`; the Action
never runs a consumer's tests).

Config is shared too: both read `.mergecraft/config.yaml` through
`config/layered.py`; the Action skips `config.local.yaml` and the checkout's `.env` because
the reviewed PR controls those files (`running_in_github_actions()`), while the CLI reads both.

Two consequences matter for testing:

- A finding-quality difference between the Action and `mergecraft review` on the same diff
  is a bug, because the prompt, tools and agents are the same.
- Fallback exists at **two** levels that behave differently. The in-process roster chain
  (`modelChain` p0 → p1 → …) walks on credential miss or retryable failure for both drivers.
  The three-rung cascade in `.github/workflows/mergecraft.yml` (OpenCode Go → Codex → Claude
  backstop) is workflow YAML and only exists in CI. Open issue #1009 documents a gap in the
  second (an expired Codex login is not failover-eligible).

Also: the CLI *writes* CI configuration. `workflow`, `provider auth --scope github`,
`tracing logfire wire-workflow` and `jev enable` edit `.github/workflows/mergecraft.yml` in
place (a line-level YAML mutator, not a YAML library) and call the `gh` binary for
`gh secret set`/`list`/`delete`. There is no GitHub REST client in the CLI for these paths;
without a logged-in `gh` they fail.

## 2. Inventory

190 nodes: 1 root, 38 groups, 151 visible leaf commands, 2 hidden (`diff-review`,
`findings _by_review_id`). 48 entries at the top level. Every option on every command has a
help string (checked programmatically). The command list in `docs/cli.md` is generated from
the live app and is in sync.

| Family | Top-level entries | Leaves |
|--------|-------------------|--------|
| Review and inspection | `review`, `plan`, `describe`, `explain`, `ask`, `replay`, `run`, `traces`, `evidence`, `findings`, `context`, `verify-behavior`, `watch` | 25 |
| Model / provider / roster | `agent`, `agent-local`, `agents`, `model`, `models`, `provider`, `auth`, `workflow` | 50 |
| Config and trust | `init`, `config`, `trust`, `jev`, `policy`, `profile`, `memory`, `learnings`, `requirements`, `xrepo` | 31 |
| Ops and diagnostics | `doctor`, `health`, `audit`, `support-bundle`, `cache`, `update`, `version`, `capabilities`, `tracing`, `gha` | 16 |
| Analyzer / lens / pipeline internals | `analyzers`, `lens`, `pipeline`, `mcp`, `opencode` | 17 |
| Evals (maintainer) | `eval` | 15 |

Half of the leaves (50 of 151) are about choosing a model or provider. That is the single
biggest usability problem and the main simplification target (Section 5).
