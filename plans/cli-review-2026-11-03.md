# mergeCraft CLI review — 2026-11-03

Scope: the `mergecraft` command-line interface (`src/mergecraft/cli/`, 70 modules, ~20,450
lines) at commit `3000d1c` on `main`, package version `0.1.0a4`. Method: full command-tree
dump from the live Typer app, offline smoke run of every leaf command, source reading of the
overlapping command families, docs coverage audit, and the project's open issues.
Companion: [`plans/cli-test-plan.md`](cli-test-plan.md) is the live-provider test campaign.

## Summary

- **Last CLI change: today, 2026-11-03** (`4e0183e`). The CLI is actively developed, not
  stale.
- **CLI and CI are the same code.** One package, one Typer app; the Action runs
  `mergecraft gha`, the laptop runs `mergecraft review`. They share the review engine,
  agents, MCP tools, analyzers and config loader, and differ only in the driver on top.
- **Size: 48 top-level entries, 151 visible commands.** Half of them are about picking a
  model or provider, through eight overlapping surfaces. Several are deprecated shims that
  still look current in help and docs.
- **Offline, most commands work.** Five crash with a traceback (`review` with no chain,
  `agent show` with no credential, `lens test` after an unregistered slug, `model add`
  and `auth gemini` on a non-TTY). `traces show` is unreachable as documented. Three
  commands write files where a user would not expect (`plan`, `analyzers docs`, `eval
  bench`), and `init` does not gitignore the `.env` the CLI writes credentials into.
- **Documentation is complete at one line per command and shallow everywhere else.** A
  third of the groups have no prose at all; internal ticket and wave ids leak into
  `--help`; `.env.example` describes a removed provider and a renamed command.
- **Simplification target: 48 → about 24 top-level entries** by deleting seven shims that
  already warn, merging twelve duplicate families behind one-release aliases, hiding the
  maintainer half of `eval`, and flattening single-verb groups (Section 5).

### Top ten fixes, in order

1. Fix the five tracebacks and make `traces show <id>` work or drop it (4.2, 4.4).
2. Make `init` write `.env` into `.gitignore`; stop `plan`/`review` leaving
   `plan-review.diff` behind; give `analyzers docs` a `--cwd`-aware path (4.3).
3. Make `agent list`, `agents list`, `provider status` and `doctor` agree on one roster
   view; fold `provider status` into `doctor` (4.4, 5.4).
4. Delete `agents setmodel/addbackupmodel/set`, `workflow agents setmodel`, `workflow
   provider harnesses`, `provider enable`, `config set models`, `diff-review`, `ask` (5.1).
5. Mark every runtime-deprecated command `deprecated=True` so `--help` and `docs/cli.md`
   say so; hide `auth <vendor>` (5.4).
6. Strip ticket and wave tokens and `sevn` from help strings; add a CI grep (5.4).
7. Rewrite `.env.example` from the provider registry (5.4).
8. Retarget `update` to PyPI (3.7).
9. Make root `--format json` the only JSON switch and give the config/roster groups JSON
   output (3.8).
10. Merge `learnings` into `memory`, `replay`/`traces` into `run`, `auth logfire` into
    `tracing logfire enable`, `agent-local` into `agent --local` (5.2).

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

## 3. Duplicate and obsolete commands

The overlap clusters below were confirmed by reading the implementing modules, not just
the help text. "Writes" says which file each command actually mutates.

### 3.1 Four ways to put a model on an agent

| Command | Writes | Status |
|---------|--------|--------|
| `agent assign-model/add-model/remove-model/create/delete/set-after/list/show` | `.mergecraft/config.yaml` `agents.<name>.modelChain`, registers the model under `providers[].models`, and wires the provider plus `with.model` into `.github/workflows/mergecraft.yml` | **Current.** `init` points users here. |
| `agent-local …` (same eight verbs) | `.mergecraft/config.local.yaml` (gitignored, ignored in Actions) | Current; built from the same factory with a target flag (`agent_local_cmd.py`). Should be `agent --local`. |
| `agents setmodel`, `agents addbackupmodel` | same `modelChain` | **Deprecated in code.** Every call prints "deprecated — use `mergecraft agent assign-model`" (`agents_cmd.py:55-60,367,407`) yet nothing in `--help` or `docs/cli.md` says so. |
| `agents set --model` | same `modelChain` head | Duplicate of `assign-model p0` without the workflow wiring. |
| `agents list`, `agents show` | read-only | `show` has unique value (prints the resolved prompt and MCP tool names). Fold into `agent show --prompt --tools`. |
| `workflow agents setmodel --agent X` | only `with.model` on a workflow step | Duplicate of `workflow model add`; the `--agent` argument is discarded (`workflow_cmd.py:727`, `_ = agent`). Safe to delete. |

### 3.2 Three model chains

There are three places a chain lives: the global `models:` list (`models set`,
`config set models`), the roster `agents.<role>.modelChain` (`agent …`), and `with.model` on
workflow steps (`workflow model add/prioritize`). `models:` is not formally legacy: it is
still the base chain every role inherits when it has no `modelChain`
(`agents/registry.py:175-181`), `init` still scaffolds it, and README still says "edit
`models:` for a fallback chain". The roster tolerates it via `_prepare_assign_slug`
(`agent_cmd.py:289-313`), which is the "preserve legacy models list" behaviour in the git
log. `model add/list/delete` is a fourth surface keyed by provider label, and
`agent assign-model` already calls it for you.

### 3.3 Credentials: deprecated shims that look current

| Command | Writes | Status |
|---------|--------|--------|
| `provider add/edit/delete/list`, `provider auth <label>` | `providers:` rows; indexed `LLM_PROVIDER_<N>_*` in `.env` and/or GitHub secrets; seeds `agents.reviewer` p0 | **Current, documented path** (README). |
| `auth claude/codex/cursor/gemini/tokenhub/opencode/minimax` | prints "deprecated — use `mergecraft provider auth`" (`auth_cmd.py:798-802`); when the label is registered it delegates to the indexed layout; otherwise writes the flat name (`CLAUDE_CODE_OAUTH_TOKEN`, `CODEX_AUTH_JSON`, `MERGECRAFT_CUSTOM_PROVIDER_API_KEY`) | **Deprecated shims**, still visible and still what `CONTRIBUTING.md`, `docs/EXIT-CODES.md` and `.env.example` tell people to run. `auth logfire` is the one non-deprecated member. |
| `provider enable` | delegates to `provider auth` (`provider_toggle.py:362-392`) | Alias. `provider disable` is the only "unset" verb and should stay. |
| `provider migrate` | converts flat `*_API_KEY` to indexed keys | One-off migration from #483. Both layouts are still read at runtime, with "registry key wins over legacy" and a one-time warning, so it cannot be deleted yet. Retire together with the flat read path. |
| `provider harnesses` vs `workflow provider harnesses` | read-only | Byte-identical function bodies (`provider_cmd.py:260-265`, `workflow_cmd.py:552-557`). |
| `provider status` vs `doctor` | read-only | `doctor` only answers "any credential present?" while `status` resolves the roster. Today they disagree in the same table (see 4.2). |

### 3.4 Tracing

- `traces <run-id>` and `traces show <run-id>` both work (group callback forwards to `show`,
  `tracing_cmd.py:302-320`); only the bare form is tested.
- `auth logfire` and `tracing logfire enable` write the same two keys and secret, but only
  the latter also writes `MERGECRAFT_TRACING_REGION` and `MERGECRAFT_TRACING=true`
  (`tracing_logfire_cmd.py:252-263`). Two code paths, divergent side effects.
- `config tracing` is a read-only "show" that lives under `config` while the writer lives
  under `tracing`; `wire-workflow` edits the workflow but lives outside `workflow`.
- The help text "Mirrors `sevn tracing logfire`" refers to a sibling product by the same
  author. It means nothing to a mergeCraft user and should go.
- `tracing_logfire_wf_yaml.py` is 1,199 lines of hand-rolled line-level YAML editing; the
  `workflow` group reuses its primitives. This is the riskiest code in the CLI: any
  consumer workflow formatted differently from the template can defeat it.

### 3.5 Same file, two vocabularies

`learnings active/staging/influence` and `memory list/show/validate/forget/export/import`
both read `.mergecraft/learnings.md` (`learnings_cmd.py:39-40`, `memory_cmd.py:33-34`).
`learnings active` is `memory list`; `influence` is `memory list` plus staging and
provenance. `memory feedback` writes a different file (`.mergecraft/feedback.json`).

### 3.6 Four readers of the same trace directory

`replay <run-id>`, `run inspect <run-id>`, `traces <run-id>` and (for a subset) `explain`
render the same JSONL events from `.mergecraft/traces` with different tables. `evidence
show/verify` reads a distinct store and is worth keeping separate.

### 3.7 Commands that do nothing or no longer fit

- `ask` returns a source line or a canned string and, by its own help, "does not call a
  model" (`ask_cmd.py:37-44`). It is a placeholder for a future verb. Delete or hide.
- `diff-review` is hidden and prints a deprecation warning; safe to delete now.
- `update` reinstalls from `git+https://github.com/alexhawat/mergeCraft@main`
  (`update_cmd.py:11-18`). Since 2026-10-27 the package is on PyPI and `docs/install.md`
  documents `uv tool install mergecraft-action==0.1.0a4`, so `update` silently moves a
  PyPI user onto the unreleased `main` tip. Retarget to `uv tool upgrade mergecraft-action`
  and keep `--branch` for the git path.
- `pipeline` (backed by `orchestrator/`) and `requirements` have no importer outside their
  own CLI module. They are islands: experimental surfaces exposed to every user.
- Single-subcommand groups with no second verb planned: `health run`,
  `support-bundle write`, `profile recommend`, `xrepo explain`, `traces show`,
  `workflow agents setmodel`. Flatten them.
- `eval`: eight of fifteen verbs (`gate`, `replay-bank`, `convergence`,
  `judge-calibration`, `bench`, `publish-benchmark`, `trajectory-score`, `trajectory-gate`)
  are called only from `Makefile`, `ci.yml` and `release.yml` against the checkout's
  `evals/cases/`. They are maintainer tooling shipped in the consumer CLI.

### 3.8 Output-format inconsistency

The root `--format table|json` is honoured by about 16 output-only commands through
`wants_json_output`. Twenty-three commands define their own `--json`/`--format`; three of
them ignore the root flag entirely (`audit export`, `provider status --json`, `version`).
Whole groups have no JSON path at all: `agent*`, `provider` (except `status`), `model`,
`models`, `config`, `trust`, `jev`, `workflow`, `policy`, `doctor`. For a tool whose
README advertises agent and script use, a JSON mode that works on a third of the commands
is a gap.

## 4. What works and what does not (offline smoke run)

Every one of the 153 leaf commands was run with `--help` (all exit 0) and then with
minimal arguments, in this checkout for read-only commands and in a throwaway git repo for
anything that writes. No provider credentials, no `gh` login, running as root. The full
per-command table is in the smoke-run notes; this section keeps what changes a decision.

### 4.1 Works offline and behaves well

`version`, `capabilities`, `describe` (deterministic, no model call), `plan`, `review
--dry-run`, `explain`, `replay`, `agent create/add-model/remove-model/set-after/delete/
assign-model/list`, `agent-local *`, `agents list/show`, `provider list/status/harnesses/
add/edit/delete/migrate`, `model list/delete`, `models list/show/set`, `workflow list/
provider add (dry run)/sync --check`, `config show/explain/validate/tracing`, `trust *`,
`jev status/enable/disable`, `tracing logfire wire-workflow/unwire-workflow` (dry-run diff
is good), `analyzers list/explain/detect`, `lens list/show`, `policy lint/effective`
(honest "no rules.yaml, showing shipped packs"), `profile recommend`, `requirements *`,
`eval list/gate` (49 cases, good JSON), `memory list/show/export`, `cache *`, `audit
export`, `support-bundle write`, `mcp list`, `opencode doctor`, `run inspect/diff`,
`traces <id>`, `health run`, `init`. Validation messages in `agent …` and `trust …` are
clear and name the allowed values. Exit codes follow `docs/EXIT-CODES.md` for the review
path.

### 4.2 Crashes (Python tracebacks)

| Command | What happens | Where |
|---------|--------------|-------|
| `review` (any live mode) with no model chain | prints a full traceback ("offline diff-review failed"), then the correct one-line message, exit 30. Before failing it pip-provisions semgrep over the network and logs "refusing to run as root" three times | `review/offline_agent.py:121` |
| `agent show <name>` whenever no credential matches the chain | `RuntimeError: no runnable model slug in chain`, Rich traceback, exit 1. A read-only show should print "(no runnable slug)". Reproduced in this repo | `cli/agent_cmd.py:458` → `utils/agent_resolve.py:712` |
| `lens test <lens> --diff f` after `models set` with an unregistered slug | `RegistryValidationError: unresolvable model slug` traceback | `cli/lens_cmd.py:86` |
| `model add <id>` without `--provider`, stdin not a TTY | falls into `typer.prompt`, "Aborted.", exit 1 | `cli/model_cmd.py:76` |
| `auth gemini --scope local`, stdin not a TTY | calls `getpass`, warns, cancels, exit 0 (reports success) | `cli/auth_cmd.py` |

`--quiet` suppresses none of these.

### 4.3 Unexpected side effects

- `plan` and `review` write `.mergecraft/plan-review.diff` into the target repo; it is not
  gitignored.
- `analyzers docs` rewrites `docs/ANALYZERS.md` **in the installed package's checkout**,
  ignoring `--cwd`. Run from any other repo it edits this one.
- `eval bench`, `eval replay-bank`, `eval convergence` create `evals/results/*.json` in
  whatever repo you are in, and report numbers ("lens macro precision 29.36%", "cases: 1")
  from bundled fixtures when the repo has zero cases.
- `analyzers lock` downloads twelve binaries (316 MB) into `~/.cache/mergecraft` with no
  prompt and no `--check`.
- `init`, `provider add`, `auth … --scope local` and `tracing logfire enable` write `.env`,
  but the `.gitignore` that `init` writes lists only `.mergecraft/*` entries. A fresh
  `init` + `provider auth --scope local` leaves a credential file untracked and visible to
  `git add -A`.
- `tracing logfire enable/disable` without `--scope local` edits `.env` first, then fails
  on a missing `origin` remote (exit 30): a partial write on failure.
- `cache` honours `HOME` but ignores `XDG_CACHE_HOME`.

### 4.4 Inconsistent or confusing

- **Three roster views disagree in this repo**: `agent list` prints an empty roster,
  `agents list` prints six roles, `provider status` shows a reviewer p0 on
  `opencode-go/deepseek-v4.1-flash`. `doctor` says "provider: no provider credentials
  detected" and "auth: 2 credential env var(s) present" in the same table.
- **Root `--format json` is ignored** by `doctor`, `plan`, `version`, `provider list`,
  `config validate`; `doctor` has no JSON output at all; `learnings active --json` prints
  plain text when the file is missing.
- **`traces show <id>` cannot be invoked as documented.** The group takes `[RUN_ID]`
  before the subcommand, so `traces show x` is "No such command 'x'" and only `traces x`
  works. `docs/cli.md` lists `traces show`.
- **Validation asymmetry**: `models set` accepts any slug; `model add` and
  `agents addbackupmodel` require a registered provider. `config set` supports four keys
  while `init` writes a dozen.
- **`memory validate` rejects the file `init` just scaffolded** ("corrupt memory store: not
  a valid memory document") while `memory list` reads it fine.
- **Error presentation varies**: `config show badkey` prints a JSON-quoted string;
  `jev set threshold 0.5` dumps raw pydantic output with an `errors.pydantic.dev` URL;
  `provider disable` leaks `git config --get remote.origin.url failed (1)`;
  `analyzers run` repeats the root-refusal message three times. "Not found" exits with 2
  (`explain`, `evidence`), 30 (`memory show`, `eval replay`), 1 (`audit verify`) or 0
  (`run inspect`, `found: False`).
- **Output style varies**: Rich tables for most lists, plain space-separated rows with no
  header for `models list` and `provider list`, Markdown for `describe`.
- `init` prints `wrote .gitignore` four times and pre-registers fourteen providers.
- `watch [REPO] --pr N`: the positional is the repository, not the PR number.
- `health run` reports `telemetry.remote_export: true` when offline.
- `analyzers detect` exits 30 for "no changed files", which is not an error.
- `pipeline explain/lint/show` exit 30 with "pipeline file not found" and no hint how to
  create one.
- `context inspect` needs five required options including `--tree-sha`.

### 4.5 Are the commands well documented?

Every option has a help string, and `docs/cli.md` is generated from the live app and is in
sync (151 rows). That is where the good news ends.

- The reference is one line per command, no options, no examples, no exit codes. Group
  help never reaches it, so the group-level jargon never gets reviewed.
- **21 of 38 groups (about 50 leaves, a third of the CLI) exist only as that one table
  row**: `agents`, `ask`, `audit`, `cache`, `capabilities`, `context`, `describe`,
  `evidence`, `gha`, `health`, `lens`, `memory`, `pipeline`, `plan`, `policy`, `profile`,
  `replay`, `requirements`, `support-bundle`, `update`, `version`, `xrepo`. `memory` (7
  leaves) and `policy` (5) have zero narrative docs.
- Nine groups are "mentioned once" (`agent-local`, `models`, `model`, `config` except
  `tracing`, `doctor`, `jev`, `analyzers`, `learnings`, `explain`). `doctor` is the
  recommended post-install step in README and no document shows what it checks or what a
  failing row means.
- Well documented: `review`, `provider auth/status`, `init`, `mcp`, `findings`, `trust`,
  `verify-behavior`, `opencode`, `auth logfire`, `workflow sync`, `agent assign-model`.
- Internal plan and ticket tokens reach users in `--help` and therefore in the generated
  docs: `(D13)` on the `eval` group, `(#44)`, `(#140)`, `(#140, B3)`, `(RC6)`, `(EV3)`,
  `(D9)`, `(B7)` on eval verbs, `(#483)` on `provider migrate`, `(D11)` on `learnings
  influence`, `(W8.4 / W7.6)` on five `review` tracing flags, `(D14)` and `(TS1 / D3)` on
  `review`, "D7 singleton secret" on `auth minimax`, and "Mirrors `sevn tracing logfire`"
  on the `tracing` groups. Two help strings leak Sphinx `:class:` roles. 49 of 153 help
  texts render RST double backticks literally.
- Deprecation is invisible: `auth <vendor>` ×7 and `agents setmodel/addbackupmodel` warn
  at runtime but look current in `--help` and `docs/cli.md`, and `CONTRIBUTING.md`,
  `docs/EXIT-CODES.md` and `.env.example` still tell users to run them.
- Stale: `.env.example` (see 5.4), `docs/verify-behavior.md:310` still says
  `diff-review`, `docs/authentication.md:221-238` presents the removed Nous provider as a
  worked example, `cli/__init__.py` mentions a `pf` entrypoint that never existed in
  `pyproject.toml`.
- There are eight documented ways to choose a model (`provider auth`, `provider add`,
  `agent assign-model`, `agent-local assign-model`, `model add`, `models set`,
  `agents setmodel`, `workflow provider/model/agents`, plus `MERGECRAFT_MODEL`). Four of
  them have zero documentation; only `docs/agent-roster.md` "Two files, two jobs" explains
  committed vs local, and it does not mention `models set` or `workflow model`.
- `review --help` is 319 lines. It is thorough but the `--help` flag sits alone in a panel
  above the groups, and the `--token`/`--shell` prose wraps mid-sentence.

### 4.6 Test coverage of the CLI

`tests/cli/` holds 116 files and 112 files repo-wide drive the Typer app through
`CliRunner`. Coverage is broad but mocks credentials, which is why `agent show` crashing
without a credential and `traces show` being unreachable went unnoticed: the tests
exercise `traces <id>` and `agent show` only with a resolvable chain. Note for whoever runs
them: `uv run pytest` picks up a global pytest and fails to import `mergecraft`; use
`uv run --extra dev python -m pytest …`.

## 5. How to simplify it

Principle: one verb per job, one place per file. The CLI mutates four files
(`.mergecraft/config.yaml`, `config.local.yaml`, `.env`, `.github/workflows/mergecraft.yml`)
and one secret store. Today the same mutation is reachable from two to four commands, which
is why half the leaves are about model selection. The plan below takes the top level from
48 entries to about 24 and the leaves from 151 to roughly 95, without removing a capability.

### 5.1 Delete now (already warning, or no behaviour)

| Remove | Users run instead | Why it is safe |
|--------|-------------------|----------------|
| `agents setmodel`, `agents addbackupmodel`, `agents set` | `agent assign-model`, `agent add-model` | runtime already prints the replacement |
| `workflow agents setmodel` | `workflow model add` | its only distinguishing option is ignored |
| `workflow provider harnesses` | `provider harnesses` | identical body |
| `provider enable` | `provider auth` | documented as a delegate |
| `config set models` | `models set` | one of two writers of the same key |
| `diff-review` | `review` | hidden and warning since 0.1.0a2 |
| `ask` | nothing | no behaviour |

### 5.2 Merge with a one-release alias

| Old | New | Notes |
|-----|-----|-------|
| `agent-local <verb>` | `agent --local <verb>` | same factory, one flag; keeps the local/committed distinction visible in help |
| `agents list`, `agents show` | `agent list`, `agent show --prompt --tools` | `agents` group disappears |
| `model add/list/delete` | `provider model add/list/delete` | they are keyed by provider label |
| `auth <vendor>` ×7 | `provider auth <label>` | hide the group, keep `auth logfire` until 5.2 row below lands |
| `auth logfire` | `tracing logfire enable` (prompts when `--token` absent) | one code path; both then set `MERGECRAFT_TRACING` |
| `config tracing` | `tracing show` | read and write in one group |
| `tracing logfire wire-workflow/unwire-workflow` | `workflow tracing enable/disable` | all workflow mutation in `workflow` |
| `workflow model prioritize` | `agent assign-model` + `workflow sync` | the roster is the source of truth |
| `traces [show] <id>`, `replay <id>`, `run inspect`, `run diff` | `run list`, `run show <id>`, `run replay <id>`, `run diff` | one reader for `.mergecraft/traces` |
| `learnings active/staging/influence` | `memory list [--staging] [--provenance]` | same file |
| `health run`, `support-bundle write`, `profile recommend`, `xrepo explain` | `health`, `support-bundle`, `profile`, `xrepo <id>` | flatten |

### 5.3 Hide from the consumer CLI

- `eval gate`, `replay-bank`, `convergence`, `judge-calibration`, `bench`,
  `publish-benchmark`, `trajectory-score`, `trajectory-gate`: mark `hidden=True` or move to
  a `mergecraft-dev` entrypoint that only the checkout installs. Keep `eval
  add/list/replay/promote/ingest/adjudicate/score` for users who keep a local failure bank.
- `pipeline` and `requirements`: hide until their packages are wired into the review path or
  removed.
- `gha`: keep, but say in its help that it is the Action entrypoint and not for humans.

### 5.4 Fix rather than remove

1. **`update`** should default to `uv tool upgrade mergecraft-action` and use the git ref
   only with `--branch`.
2. **`doctor`** should absorb `provider status` (or call it) so the two never disagree, and
   its "analyzer 0/70 would enable" line should say why (shell permission is `disabled` by
   default) instead of looking like a broken install.
3. **Root `--format json`** should be the only JSON switch. Remove per-command `--json` and
   `--format` after making `audit export`, `provider status` and `version` read the root
   option, then add JSON output to `agent list`, `provider list`, `models show`,
   `config show`, `trust show`, `jev status`, `doctor`.
4. **Help text** must lose the plan and ticket tokens that reach users: `(D13)`, `(#44)`,
   `(#140, B3)`, `(RC6)`, `(#483)`, `(W8.4 / W7.6)` on five `review` tracing flags, and
   `sevn`. A check that greps rendered `--help` for `\(#\d+|\bD\d+\b|\bW\d+|\bRC\d|sevn`
   belongs next to `make docs-check`, because `docs/cli.md` is generated from these strings.
5. **`.env.example`** is the most stale consumer file in the repo: it calls `mergecraft run`
   the review verb, names the removed Nous provider as "primary", sets
   `MERGECRAFT_MODEL=nous/…`, and documents an internal "meat" spike. Regenerate it from the
   provider registry or delete it in favour of `provider auth --scope local`.
6. **Deprecation must be visible in `--help`.** Anything that warns at runtime should carry
   `deprecated=True` (Typer renders it) so the generated reference shows it.

### 5.5 Target top level (24 entries)

`init`, `doctor`, `review`, `plan`, `describe`, `explain`, `verify-behavior`, `watch`,
`run`, `evidence`, `findings`, `agent`, `provider`, `models`, `workflow`, `config`, `trust`,
`policy`, `memory`, `analyzers`, `tracing`, `mcp`, `eval`, `version`; plus the kept-but-minor
`jev`, `opencode`, `lens`, `context`, `xrepo`, `capabilities`, `cache`, `audit`, `health`,
`support-bundle`, `profile`, `update`, `gha`. The second list is where a `mergecraft
--advanced` help filter or a "More commands" section in `--help` would pay off: the
interactive TTY menu already groups commands, and the same grouping should drive the
non-interactive help.

## 6. Known open issues that touch the CLI's review path

- #1132 (2026-11-03): a run that submits a verdict and publishes still ends "opencode
  failed" with `Outcome: failed`. Affects `review` exit codes on the opencode harness.
- #1131 (2026-11-03): inline review comments rejected with HTTP 422 because threads carry a
  fingerprint field (Action publish path; not reachable from `review`).
- #1009 (2026-10-17): an expired Codex credential is not failover-eligible, so the chain does
  not move on. Directly relevant to the fallback tests in the companion plan.
- PR #1125 (open): "cascade failover and gate unknowns" changes the failover semantics the
  test plan exercises. Re-run section 5.D of the plan after it merges.
