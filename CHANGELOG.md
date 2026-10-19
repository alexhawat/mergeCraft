# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Reviews now read the materialised diff first. Review and IncrementalReview
  render a shared hard instruction: `diffPath` (or `incrementalDiffPath`) is the
  authoritative review scope, `git diff` / `git grep` / `git log` must not be used
  to reconstruct it, and independent reads are batched into one turn. The
  instruction is rendered for every consumer, not only this repository's
  workflow.
- Diff line-range coverage: `changed-unread-file` reports the unread added-line
  ranges (`path:start-end`) instead of whole files, and `submit_review_verdict`
  nudges once with exactly those ranges before accepting the verdict. Reads of
  the diff file itself count (recorded as `diff_read_path` / `diff_read`), and a
  run with no observed reads is *unknown*, not unread. Deletion-only and
  mode-only sections stay in scope and are named until their path is read.
- A no-output/idle watchdog for CLI agent drivers: no parsed event for
  `agentIdleTimeout` seconds (default `900`, `0` disables) kills the attempt and
  reports the idle span, event count, whether the model produced output, the last
  provider error, and the stderr tail. The attempt still fails so the chain can
  advance, but the run outcome is `infra_error`, not a failed review.
- `run_metrics` on the merge evidence packet (schema `1.15.0`): tool calls, read
  calls and read turns, distinct files read, diff line counts, elapsed by phase
  (setup / analyzers / agent / judge / publish), and the last watchdog
  diagnostic. The deterministic run record renders it as a **Review cost** row.
  Measurement only — it never feeds the gate.
- Bounded file-group fan-out planner (`review/file_group_fanout.py`): a large
  diff splits into at most six balanced read-only groups, and a failed group is
  recorded rather than raised. Planning and degradation only; it is not wired
  into server-side roster dispatch in this release.
- Analyzer disposition ledger: every raw analyzer hit gets a stable `hit_id` and
  ends `kept`, `merged`, `downgraded` or `dropped:<stage>` with a required reason.
  The merge evidence packet (schema `1.14.0`) carries the ledger, per-stage counts
  and the baseline-suppression audit rows that were previously only logged; the
  pre-merge Analyzers row reads like `ruff 14 raw → 3 kept (9 out_of_scope, 2
  baseline)`. SARIF ingested via `ciEvidence.sarifArtifacts` follows the same
  contract (#941).
- `self-silencing` analyzer (in-process, every trust tier, no shell): reports added
  suppression markers (`# nosec`, `# noqa`, `// eslint-disable-next-line`,
  `#[allow(..)]`, `//nolint`, …) with the rule codes they silence, and loosening
  edits to `.mergecraft/config.yaml`, `ruff.toml` / `pyproject.toml`, ESLint config
  and scanner ignore files. Edits to `.mergecraft/**` and analyzer/linter config
  also keep a PR out of the `eligible` blast-radius lane (#942).
- `analyze_ci_failures` reads the base branch's recent runs itself, so a
  same-fingerprint base failure clears a failure as pre-existing with no
  agent-supplied arguments; the runs it used are recorded in the result and the CI
  evidence. A passing or unrecognised base status never clears one (#891).
- Opt-in `gherkin-lint` catalog analyzer: syntax and structure lint for changed
  `.feature` files, run through the repo's own pinned `gherkin-lint`. Disabled by
  default because the catalog has no managed npm runtime; enable it with
  `analyzers.overrides.gherkin-lint.enabled: true` (#854).

### Changed

- Incremental re-review is the default on a re-review. `checkout_pr` now computes
  the range whenever a prior reviewed sha is recoverable — not only when
  `select_mode` chose IncrementalReview — and reports
  `incrementalDiffStatus` (`ok` / `empty` / `unavailable`) with
  `incrementalDiffReason` and `lastReviewedSha`. When the range exists it is the
  review scope; the full diff is for anchoring only.
- The merge evidence packet schema is `1.15.0`; the trajectory record schema is
  `1.1.0` (optional `diff_read_path`, `diff_read`, `duration_ms` on a tool-call
  row, all omitted while unset).
- A PR's own `analyzers.*` configuration no longer applies to its own review. The
  analyzer settings (`enabled`, `overrides.<id>.enabled`, the `antislop` `rules` and
  `ignore`, `baseComparison`, `inlineBudget`, `impact`) are resolved from the PR's
  base — the operator-owned base snapshot, or the base commit's
  `.mergecraft/config.yaml` — and a head-side change is reported by
  `self-silencing` instead of applied. A symlinked or unreadable base config falls
  back to built-in defaults with a named reason. **Fix:** land analyzer-config
  changes in their own PR; they take effect from the next PR on (#942).

- A run whose analyzer disposition ledger is open — a pipeline stage lost a raw hit
  without recording why — now ends with a `neutral` approval conclusion instead of
  possibly `success`, and a run-scoped finding names the orphaned hits. A blocker
  still outranks it. **Fix:** none for consumers; the finding names the stage to fix
  (#941).

### Fixed

- A workspace review no longer fails closed with "checkout integrity failure:
  tree changed during read-only review" when dependency prep creates nested
  `node_modules`. pnpm/yarn/npm lay down `apps/api/node_modules`,
  `packages/*/node_modules` and the like (and pnpm can drop `.pnpm-store`
  in-tree), all after the integrity baseline, so the hash now prunes those
  directory names at any depth instead of only at the checkout root. A nested
  `.git` metadata directory is pruned the same way.
- Multi-reviewer rosters now dispatch secondary reviewers server-side when the
  primary harness never spawns them, fail closed with a clear error when a
  secondary cannot reach its provider, and always emit the `⏱ LLM review time`
  line (including a zero-second fallback when no LLM calls were timed).
- Exporting findings no longer crashes when a model supplies a slug-style
  `fingerprint`; non-hex values are normalized to a stable lowercase hex digest
  at write time.
- `submit_review_verdict` drops malformed draft findings instead of rejecting
  the whole terminal submission when one pre-recorded row is invalid.
- Checkout integrity hashing skips nested `node_modules`, `.pnpm-store`, run
  `evidence`, and OpenCode session dirs at any depth so harness scratch writes
  during read-only review no longer trigger exit 12.
- A review whose agent submits a verdict without calling `select_mode` now
  publishes the formal review with the run record. Before, the PR got only a
  short progress comment, with no tokens, cost, timing or findings, whenever the
  OpenCode Go rung answered and the Codex fallback did not run.
- The run record on the formal review shows the `Cost:` line. Cost was computed
  but only reached the step summary.
- agentsec no longer reads a changed instruction or MCP manifest whose symlink
  resolves outside the repository root; the refusal is logged and reported as a
  named skip when it was the only candidate (#851).
- Numeric metadata such as `input_tokens=120` survives log redaction; credential
  named keys and long numeric runs still redact (#877).
- Trusted-tier catalog analyzers drop to the agent UID on the root backend, with
  their scratch tree and the baseline worktree handed to that UID first; an
  unlandable drop reports `unavailable` instead of running as root (#878).
- `run_checks` refuses to run an untrusted static gate without a sandbox context,
  whatever `shell` says, so the executor fails closed even if a caller does not
  (#887).

## [0.1.0a3] — 2026-10-17

### Breaking — action required

- The built-in Nous Portal provider is gone: the `nous/...` catalog models,
  `mergecraft auth nous`, and the flat `NOUS_API_KEY` credential no longer
  exist, so a `nous/...` model now fails as an unregistered provider. **Fix:**
  register Nous (or any OpenAI-compatible endpoint) under `providers:` in
  `.mergecraft/config.yaml` with `url`, `harness: opencode` and an `envIndex`,
  and pass the key as `LLM_PROVIDER_<N>_API_KEY`. See
  [docs/authentication.md](docs/authentication.md).

- An invalid `trust.agentSandbox` value (for example `off`, a bare `false`, or a
  typo like `nevr`) now fails configuration validation instead of quietly
  becoming `dispatch`. **Fix:** set one of `never`, `merged-only`, `dispatch`, or
  `same-repo`; the four tiers still normalize whitespace and case.

- The `model_pin` action input no longer carries a default. Leaving it unset
  follows the repository's `modelPin` setting, and an explicit `disabled` now
  overrides a repository `modelPin: true`. **Fix:** leave `model_pin` unset to
  follow the repository, or set `enabled` / `disabled` explicitly; the previous
  `disabled` default meant an unset input could never override the repository.

- Settings the standalone runtime does not consume are accepted but now warn
  once when set to a non-default value: `gates.thermostat`, `tracing.redaction`,
  `stopScript`, `blastRadiusOverride`, `operatorPipeline`, and `autoMergeEnabled:
  true`. **Fix:** none required — the values still parse and round-trip; remove
  the key if the warning is unwanted.

- A malformed tracing environment variable or tracing Action input — the enable
  flag, the region, the content level, or the untrusted-content export — now
  fails configuration instead of being ignored. A typo such as `flase` used to
  drop the value and let a lower layer's more permissive one win; the run now
  fails closed as a configuration error naming the variable, and never prints
  its value. **Fix:** correct the spelling; `MERGECRAFT_TRACING_REGION` still
  accepts `us` and `eu`.

- The MCP server no longer mounts a webhook endpoint. **Fix:** none — a signed
  delivery was verified but processed nothing, and its replay window could never
  fire, so no review path consumed the route.

- Provider circuit-breaker, health, budget and routing-eval helpers that no
  review path called are removed. **Fix:** none — none of them was reachable
  from a review.

- Four context-retrieval modules no review path imported are removed. **Fix:**
  none — no review path imported them.

- Agent entries with `dispatch: ensemble` or `shadow` are refused as not
  implemented instead of being accepted and ignored. **Fix:** use a `dispatch`
  mode that is implemented; `ensemble` and `shadow` are refused.

- The `sarif_upload` action input no longer declares a default, so an unset
  input reaches `.mergecraft/config.yaml`'s `analyzers.sarifUpload` as
  intended. **Fix:** set `sarif_upload` (or `analyzers.sarifUpload`) explicitly
  if you relied on the implicit `disabled`.

- Progress comments are recognised by the identity that published them, not by
  any bot. When neither the expected publisher nor a trusted self-review sticky
  id is available, the run creates a new progress comment — and with it a fresh
  ledger — rather than adopting a comment posted by the shared Actions bot.
  **Fix:** none required; pin the reviewer App (or the self-review workflow) if
  you want the existing sticky adopted.

- Enterprise audit events are no longer written to `.mergecraft/audit.jsonl`
  inside the workspace by default. **Fix:** set `MERGECRAFT_AUDIT_ROOT`, or read
  from the new default location.

- Every exit under `src/mergecraft/cli/` now routes through named constants and
  usage errors exit `2`. **Fix:** scripts that branched on exit code `1` for
  generic CLI failures must follow the new table — most former `1` paths now
  exit `30`; see [`docs/EXIT-CODES.md`](docs/EXIT-CODES.md).

### Known limitations

- Evaluation in this release is structural replay only, not live detection, and
  no human-adjudicated, calibrated or benchmarked result ships in it.

Full long-form history, including the entries condensed or omitted here:
[docs/dev/changelog-archive.md](docs/dev/changelog-archive.md#010a3--long-form-entries).

### Added

- Code-measured LLM review generation time in every posted review record and CLI JSON/text output (`⏱ LLM review time: …`), including per-reviewer breakdown when multiple reviewers run (#983).

- `mergecraft agent assign-model` on the committed roster registers missing models, auto-wires harness providers into `mergecraft.yml`, and updates `with.model` for p0 assignments.

- Human golden-batch manifests declare their own batch id and case list, so a later batch can be reviewed without a code change; the first batch's nine case ids stay pinned as a frozen fixture.

- Behaviour-verification reports record which driver produced them — `cdp`, `stub`, or unset when not recorded — so a report says whether its page came from a real browser or the non-browser fallback.

- `docs/opencode.md` documents the integration: engine selection, commands, subagents, V2 MCP wiring, JEV scope, and Logfire tracing.

- `mergecraft verify-behavior` can reproduce a bug or check a running app and write a versioned report under `.mergecraft/artifacts/`.

- A versioned behaviour-verification report (`schema_version` 1.0.0) records what was observed, which criteria passed, and what blocked the run — without turning those results into code findings (#61)

- Reviews can ingest declared coverage receipts and report change-risk scores on the functions the PR actually touched, advisory by default (#714)

- Opt-in Jev / System One client (`jev.enabled`, default off) with cost accounting, a kill-switch, and GenAI spans; a missing TypeSafe key records a skip and does not fail the review (#728)

- Parallel shadow judge grades review findings and prose against their cited evidence without replacing the reviewer (#728)

- `mergecraft review --tracing-content` and Action `tracing-content` set the capture level without editing YAML

- Multiple reviewer-role bindings run on one PR; findings merge by path/body/line and produce exactly one verdict with strictest severity winning

- `mergecraft workflow sync` keeps `.github/workflows/mergecraft.yml` auth wiring aligned with roster models; unwired providers fail at CLI write time and at run start

- First `mergecraft provider auth` after `init` seeds `agents.reviewer` p0 so review works with no third command

- `docs/agent-roster.md` — operator guide for slots, named agents, local scope, multi-reviewer verdict rules, and the run-start trust snapshot

- `establish_review_scope` — evidence-backed second route into review scope when a materialized diff already describes the PR head

- Read-only git MCP verbs (`show-ref`, `for-each-ref`, `ls-remote`, `config --get`) and `checkout_pr` parameter aliases (`pr_number`, `issue_number`)

- Agent stream logs render human-readable lines instead of dumping raw provider NDJSON.

- `Finding.scope` (`change` | `run`, default `change`) and `FindingSource` `"trajectory"` so trajectory auditor rows are attributed as process evidence, not PR defects

- Job step summary (`GITHUB_STEP_SUMMARY`) written from `_publish` with outcome, pre-merge rows, and findings — capped at GitHub's 1 MiB with the header intact

- Evidence packet persisted to a workflow artifact on every review rung (`if: always`, 30-day retention) so the packet survives runner teardown

- `MERGECRAFT_ACTION_SHA` workflow variable — one pin definition shared by all three review rungs, with `make action-pin-check` enforcing staleness and rung parity (#532)

- Action image digest pin gate (`action-image-digest-check`) and halved `wait-for-ci` poll cadence (20s → 10s, #528)

- `mergecraft tracing logfire wire-workflow --region us|eu` writes `MERGECRAFT_TRACING_REGION` into the wired step's `env:`.

- `mergecraft provider disable <label>` clears a provider's credentials so GitHub CI stops using it, without hand-editing secrets or workflow YAML.

- `mergecraft provider enable <label>` names the authenticate half of that toggle; it delegates to the existing `provider auth` flow (#520)

- Offline public MCP tool-selection eval corpus under ``evals/mcp-public/`` with fixture prompts and deterministic scorer ``mergecraft.evals.mcp_public`` (no live LLM in ``make test``)

- `make action-pin-check` also measures the pin against the default branch's own tip, not just against the other branch's pin.

- `make action-pin-check` guards the self-review Action pin against drift.

- Open-PR finding ledger in the sticky progress comment — `mergecraft findings ledger --pr N` inspects inline, deferred, withdrawn, and unpublished fingerprints without filing GitHub issues

- Optional recall pass (`review.recallPass`, default off) dispatches `mergecraft-recall` after aggregation; novel findings always publish in the deferred lane

- Optional round-aware budgets (`review.roundBudgets`) scale token, cost, tool-call, and subagent ceilings by review round; defaults stay flat until opted in

- Lens execution recording on `ToolState`, review metadata, and merge-evidence packets; findings may carry optional `lens` attribution

- Collateral lists on `Critical` and `Major` findings name callers, tests, and other files that must move with the fix; inline comments render them under **Also update:**

- `make lint` checks that jobs calling local reusable workflows grant at least the permissions the callee declares, catching ``startup_failure`` permission mismatches at authoring time (#425)

- Consumer glossary (`docs/glossary.md`) — plain-language definitions for trust tier, typed findings, blast radius, and related landing-page terms; manifest row and `llms.txt` entry.

- Runnable CLI example trees under `examples/cli/` (local diff, branch range, patch file, and `--agent` JSONL) with `make cli-examples` / `cli-examples-check` and `docs/cli-examples.md` tour page

- Agent-loop reference workflow (`docs/agent-loop.md`) for `mergecraft review --agent` (#383)

- CLI and GitHub Action runs now enter one review engine over one immutable snapshot (#380)

- `mergecraft explain`, `ask`, and `replay` plus `run inspect` / `run diff` print output-only change, line Q&A, and stored-run views (#377)

- `mergecraft review --agent` negotiates protocol version against CLI JSON `schema_version` (both fields kept, aliased), reports retryable mismatches, and names token/cost/tool-call budgets (#379)

- `mergecraft review --agent` streams the first finding before the verdict; `--use-cache` and `--resume` reuse a local result cache; cancelling a review cleans up child processes (#378)

- `llms-full.txt` generated concatenation plus docs pin/link gate (`make llms-check`, folded into `make docs-check`).

- Added: generated CLI and Action reference pages (`docs/cli.md`, `docs/action-reference.md`) plus a docs manifest; `make docs-check` replaces landing-README table splices.

- Review specialists now report unique useful findings plus latency, cost, precision, and recall (#370)

- `.mergecraft/config.yaml` now carries a `schema_version`; unversioned files migrate on load, unknown versions fail closed, and deprecated keys warn before a breaking removal (#368)

- `mergecraft doctor --supply-chain` verifies lockfile reproducibility, bundled agent-CLI provenance, and analyzer version pins; every run manifest now records runtime and tool versions (#366)

- `mergecraft requirements inspect` and `explain` map ticket and local-spec text to requirement states without writing the reviewed tree; policy can require that evidence before a review passes (#352)

- `mergecraft describe` prints an output-only PR title, summary, walkthrough, risk, labels, TODOs, effort band, split advice, and similar-change notes (#351)

- `mergecraft capabilities` prints the review-only capability manifest (modes Review, IncrementalReview, Plan; identify / investigate / verify / explain / prioritize / suggest) (#350)

- Python 3.11 floor ADR (#343, option A): `docs/dev/python-version-floor.md` records parenthesize-now / binary-later.

- `osv-scanner` detect globs now include `uv.lock`, so repos using uv's lock file trigger vulnerability scanning without pip-audit (#309)

- docs: `flake8` and `pylint` catalog entries note they are legacy opt-in; enabled via config override only (#309)

- Catalog manifests for `knip` (JS/TS unused exports/dependencies, `scope: repo`, `category: quality`) and `vulture` (Python dead code, `scope: repo`, `category: quality`) (#337)

- `detekt` flipped to `default_enabled: auto`; activates on any `*.kt` or `*.kts` change, or when `detekt.yml` is detected — provides the default Kotlin lint path (#317)

- `sqlfluff` flipped to `default_enabled: auto`; activates on any `*.sql` change or `.sqlfluff` config presence — skips silently when no SQL dialect is declared (#319)

- `stylelint` flipped to `default_enabled: auto`; activates on any `*.css`/`*.scss` change or `stylelint.config.js`/`.stylelintrc.json` presence — provides the default CSS lint path (#320)

- `htmlhint` flipped to `default_enabled: auto`; activates on any `*.html` change or `.htmlhintrc` presence — provides the default HTML lint path (#321)

- `checkmake` flipped to `default_enabled: auto`; activates on any `Makefile`, `makefile`, or `*.mk` change — provides the default Make lint path (#325)

- `markdownlint` flipped to `default_enabled: auto`; activates on any `*.md` change or `.markdownlint.json`/`.markdownlint.yaml` presence — provides the default Markdown lint path (#326)

- `luacheck` flipped to `default_enabled: auto`; activates on any `*.lua` change or `.luacheckrc` presence — provides the default Lua lint path (#328)

- `fortitude` flipped to `default_enabled: auto`; activates on Fortran files (`*.f90`, `*.f95`, `*.`, `*.f03`, `*.f`, `*.for`) or `.fortitude.toml` — provides the default Fortran lint path (#329)

- `regal` flipped to `default_enabled: auto`; activates on any `*.rego` change — provides the default Rego/OPA policy lint path (#330)

- `psscriptanalyzer` flipped to `default_enabled: auto`, adds `*.psd1` detect glob, and sets `supports_fix: true` — provides the default PowerShell lint and auto-fix path (#331)

- `blinter` flipped to `default_enabled: auto`; activates on `*.bat`/`*.cmd` changes — provides the default Windows Batch lint path (#332)

- `smarty-lint` flipped to `default_enabled: auto`; `ANALYZERS.md` notes that `*.tpl` is ambiguous (Go templates, Terraform) — enable only when `.smarty-lint.json` confirms Smarty intent (#334)

- `ember-template-lint` flipped to `default_enabled: auto`, sets `supports_fix: true`; gates on `ember-cli-build.js` or `ember-source` in `package.json` — bare `*.hbs` files do not trigger it (#335)

- `phpcs` and `phpmd` remain `default_enabled: false`; catalog entries note they are legacy opt-in — `phpstan` (auto) is the default PHP signal (#316)

- `brakeman` flipped to `default_enabled: auto` with tight Rails detection — only activates on Rails marker files (`config/application.rb`, `config/routes.rb`), never on plain Ruby repos (#313)

- New catalog manifest for `bundler-audit` (Ruby gem vulnerability audit, `category: vuln`, `scope: repo`, detects on `Gemfile.lock`) (#313)

- `scripts/check_type_ignores.py` fails when a `type: ignore` or `cast(` in allowed `src/mergecraft/` lacks a one-line reason (#275); wired into `make lint`

- `scripts/check_xpass.py` fails when unexpected pytest xpasses remain on the allowed test tree (#276)

- xpass ratchet now runs as a `pytest_sessionfinish` conftest hook inside the coverage-gate pytest session — no standalone log file or extra CI step (#276)

- docs: README requirements and `docs/distribution.md` Marketplace copy state that mergeCraft 0.1.0 is GitHub-only; GitLab support is planned via the `ScmProvider` abstraction (#279)

- Added: a test-only provider-harness fixture schema and strict matcher (`tests/support/provider_harness`) so deterministic review tests can name the exact provider interaction they expect.

- Added: provider-harness recording workflow and operator docs (`docs/dev/provider-harness.md`); opt-in sanitized capture under.

- Repository context engine indexes per-file symbols (tree-sitter with generic fallback), provenance citations, and trust-gated instruction/skill discovery under `mergecraft.context`

- Call graph, change graph (changed symbol → dependents → tests → contracts), and `mergecraft context inspect` for provenance-backed context retrieval

- `mergecraft policy lint|test|explain` — validate policy rules, run should-trigger/should-not fixtures, and list effective rules with source layers

- Per-run budgets, bounded external-operation timeouts, and honest large-diff degradation (`RunBounds`, scope reduction reports, downgraded outcomes) for offline and Action reviews

- precision corpus gate (`evaluate_dg1_precision_corpus`) replays the corpus and compares confirmed precision against the pre-DG1 baseline

- `mergecraft mcp serve` and `mergecraft mcp list` expose the reviewer's MCP tool surface to external clients without widening trust tier or tool-class policy

- Named review profiles (`--profile fast|deep|security`) bundle model chain, analyzer focus, and run budgets; explicit CLI flags still win

- `mergecraft cache info|clear|prune` inspect and maintain the byte-bounded on-disk run cache

- `mergecraft doctor` diagnoses git, provider credentials, analyzer detection, auth, config, and MCP port availability without printing secrets

- `mergecraft config show|explain|validate` generalizes precedence inspection beyond tracing; local private-repo reviews ship no remote telemetry by default

- `mergecraft plan` previews model chain, toolset, analyzer detection, and token estimate without provider calls

- Run manifest fingerprints (model/CLI versions plus prompt, config, and policy hashes) for reproducible offline reviews

- `mergecraft review` machine contract: distinct process exit codes per `RunOutcome`, `--format text|json|jsonl|sarif`, and `--agent` JSONL streaming with an explicit `protocol_version`

- Added tracer baseline attributes (`mergecraft.run_id`, `mergecraft.version`, `mergecraft.trust_tier`, VCS and CI fields) merged into spans at close time, with explicit attributes taking precedence

- Added review-context env propagation into spawned agent CLI subprocesses, so subagent runs join the parent review's trace identity

- Added richer tool-call tracing: `gen_ai.tool.call.id` correlating request and response, per-call duration, and an MCP-vs-native origin distinction

- Added `mergecraft eval gate` — a release regression gate comparing a candidate result set against baseline with a declared tolerance band, wired as a blocking job in the release workflow

- Added agent registry binding model, prompt, toolset and budget per role with `mergecraft agents list|show|set` and `make agents-check`

- Added registry-driven harness render for Claude, OpenCode, Codex, Gemini, and Cursor with per-agent models and declared Codex degradation in run metadata

- Added typed specialist handoff and model-diversity policy for verification.

- Added change classifier and risk-based lens routing with recorded per-lens reasons in Review mode

- Promoted 20 themed review lenses from Review prose into registry entries with `mergecraft lens list|show|test`

- Added pluggable orchestrator with declarative pipeline file, trust gate for untrusted sources, and `mergecraft pipeline lint|show|explain`

- Added declared decision nodes for hybrid orchestration — typed triviality, lens selection, and finding disposition seams with pipeline-owned control flow

- Added: optional `harness` setting (`opencode` / `codex` / `claude` / `gemini` / `cursor`) to select the agent runtime independently of provider/model.

- Added: terminal-verdict protocol shadow mode (`gates.terminal_verdict`, default `shadow`) with a closed `VerdictDiagnostic` vocabulary; enforce still applies the fail-closed missing-verdict branch

- Added: `submit_review_verdict` — a typed MCP operation that records a review's terminal verdict (`approve` / `request_changes`), summary and structured findings.

- Published Python distributions are installed outside the checkout and carry build provenance before upload

- `pre-commit` blocks newly added large files and private keys, and scans staged changes for secrets with `gitleaks`

- `make test-durations` refreshes the committed `.test_durations` that least-duration sharding balances by

### Changed

- Agent entries with `dispatch: ensemble` or `shadow` are refused as not implemented instead of being accepted and ignored.

- `mergecraft policy` help and enforcement docs state that a review run does not enforce policy rules.

- Recorded Jev transports and the canary assertion moved out of the runtime package into the test suite.

- A prepared release branch keeps `server.json`'s advertised package version in step with `pyproject.toml`, so the branch no longer fails its own `mcp-server-json-check` drift gate.

- The local `.env` file and the tracing environment layer are read through one typed model each, so a variable's exact name and type live in one place and a new environment read has a defined home.

- The Gemini and Codex harness deny lists name the `push_branch` tool the way each CLI documents it, matching the spelling the other harnesses already used.

- Finding matching against a baseline maximises the number of matched issues, so recall no longer changes when baseline issues are reordered; the scorer version is now `1.1.0`.

- `mergecraft verify-behavior` now drives a real Chrome over the DevTools Protocol and scores each acceptance criterion and reproduction claim through Jev, instead of refusing every run.

- `mergecraft jev enable|disable|status|set` configures the Jev advisory screening gate.

- Order-dependent test coupling now surfaces on a scheduled, non-blocking unit-suite run whose seed is the per-run `github.run_id`, so a pinned seed no longer hides it.

- Bare CLI command names open a TTY interactive session.

- A second gate policy (prompt 2.0.0) records through the existing recorder.

- Production false positives and human dismissals can be ingested into the eval bank as versioned cases, each carrying explicit provenance.

- Consumer setup guidance now lists every file produced by `mergecraft init` that may be committed: the config, learnings file, workflow, and added `.gitignore` lines.

- CLI `--json` payloads carry their own schema version, decoupled from the review snapshot's. Both stay `1.0.0`, so no payload changes; the two can now be bumped independently (#777).

- `mergecraft jev enable` now requests `TYPESAFE_API_KEY` when it is not already set and writes it to `.env`.

- Review records, sticky progress comments, and the Actions step summary now show input and output token counts separately instead of one combined total (#801)

- `make test` no longer runs the nine branch-walking `test_cov_*` suites: they carry a new `coverage` marker and the `make test` selector is now `-m "not integration and not coverage"`.

- The coverage/mutation CI gate's `enforce` mode is now exercised under test — both `shadow` and `enforce`, asserting the gate action and `reaches`.

- The action-pin bump workflow no longer advertises a push it cannot perform.

- PR #742 drops Playwright as the behaviour-verification driver.

- `mergecraft verify-behavior` fails closed when the browser-use stack is unavailable, even with `--artifacts-dir` / `--input`; `--allow-stub` is the only stub opt-in (#61, #752)

- `verify_behavior.enabled: false` skips the run (kill switch); default remains enabled so invoking the CLI still runs on a trusted checkout (#61)

- `verify_candidate` verifies the commit that introduced an image digest rather than whichever commit the candidate range happens to end at.

- `trust.agentSandbox` ladder (`never` / `merged-only` / `dispatch` / `same-repo`) with `mergecraft trust show` and `mergecraft trust set-agent-sandbox` (#553)

- `docs/trust-policy.md` documents the sandbox override ladder, fork floor, and residual risks

- Action `logfire-token` exports to `MERGECRAFT_LOGFIRE_TOKEN` before the Logfire sink initialises (#551)

- Actions-visible warning when tracing targets Logfire but no token resolves (#551) #### Fixed

- Self-review on PRs that edit `.mergecraft/config.yaml` publishes again after the publication guard re-baselines the config hash post-`checkout_pr` (#584)

- Nous and custom gateway providers are detected when only `MERGECRAFT_CUSTOM_PROVIDER_API_KEY` is set (#552)

- Bubblewrap namespace failures surface once as a non-blocking run observation instead of inflating the packet gate with repeated Major findings (#553)

- Entropy redaction no longer strips proven benign analyzer shapes — sweep evidence at `docs/dev/15-w6-entropy-sweep-report.json` (#537) #### Changed

- #553 boundary amended from the `pull_request_target` event to fork heads — same-repo `pull_request_target` may grant the override at `same-repo` tier

- Claude backstop no longer runs when an earlier rung succeeds or posts a verdict including `neutral` — only retryable rung failures without a verdict trigger Claude (#600) #### Changed

- Same-repo `pull_request_target` self-review runs trusted-tier analyzers when `trust.selfReview` is `analyzers` — execution trust without widening approval authority

- Declared CI SARIF artifacts are downloaded and recorded when `wait-for-ci` reaches `state=complete` (green or red).

- Action log phases (setup, model chain, agent dispatch, publish) emit collapsible `::group::` blocks in GitHub Actions logs #### Added

- Dogfood config sets `trust.agentSandbox: same-repo` so Codex `danger-full-access` is honoured on same-repo review runs (#553)

- CI SARIF ingest covers actionlint, zizmor, semgrep, and trufflehog alongside ruff, mypy, and bandit — matching `ci.yml` uploads and `ciEvidence.sarifArtifacts` (#464)

- TruffleHog CI evidence converts JSONL to SARIF so a clean scan uploads a valid empty-results document with tool metadata, not a blank file

- Hardened consumer template forwards wait-for-ci outputs and grants `actions: read` for ciEvidence SARIF ingest

- `evals/README.md` Harbor install pin is `v0.1.0a1`, and live detection is documented as `mergecraft review` (Harbor still calls the hidden `diff-review` alias)

- AGENTS.md and the consumer skill match the default workflow triggers

- The self-review Action pin on all three review rungs moves to `93a7897c`, pin 5 — GitHub Action Logfire honors `MERGECRAFT_TRACING_REGION` (#607)

- Self-review Codex fallback uses `openai/gpt-terra` (GPT 5.6 Terra) instead of `openai/gpt-codex`

- Dogfood `trust.selfReview` / `trust.agentSandbox` knobs apply after merge to the default branch — `pull_request_target` reads the base config snapshot, not the PR head

- `runBounds.tokenBudget` is the soft target; `tokenBudgetTolerance` (default `0.10`) sets the hard ceiling — set tolerance `0` to restore strict enforcement

- Run record and job step summary token lines name target, ceiling, over-target status, and per-phase attribution when phases are recorded

- Policy enforcement modes score a rule's blocking intent from the finding's gate-facing severity, so ``contributes_blocker`` is read off it rather than computed beside it.

- Render path: skip short-id assignment for non-hex fingerprints instead of aborting review output; export and explain paths stay strict (#493)

- Cheat-signature lint: narrow ``getattr_tautology`` to ``object`` targets so legitimate missing-attribute fallback asserts are not flagged; severity stays ``error`` (#501)

- Coverage ratchet: merge-base lookup failures and lowered-floor comparison failures are mutually exclusive, so honesty tests can assert which guard fired (#503)

- Coverage ratchet: document that the merge-base lowering guard is PR-only on ``push`` / ``workflow_dispatch``; absolute ``fail_under`` checks still run on all events (#506)

- Coverage ratchet: pin ``_default_base_branch`` resolution order (``GITHUB_BASE_REF`` → ``GITHUB_REF`` branch → ``pre-0.0.1``) without requiring a git remote (#507)

- **Breaking:** enterprise audit events are no longer written to ``.mergecraft/audit.jsonl`` inside the workspace by default; set ``MERGECRAFT_AUDIT_ROOT`` or read from the new default location

- Analyzer and trace redactors now emit the shared ``<redacted>`` placeholder from ``mergecraft.redaction_sentinel`` instead of the legacy ``[REDACTED]`` analyzer spelling

- Overflow agent findings now append to a server-written `### 🗂 Deferred findings` section with full finding text (non-blocking); analyzer overflow remains in `### 🔧 Mechanical findings`

- `review.verificationBudget` (default 24; `0` = no cap) caps verifier dispatches independently of `analyzers.inlineBudget`

- Harbor `MergecraftReviewAgent` resolves the default `uv tool install` ref lazily in `install` via `action_pin_minimal` instead of calling it at module import (#403)

- Landing README promoted from `readme_test.md` draft: agent-first layout, glossary links, auth table with recommended models, CLI how-it-works section, and `v0.1.0a1` Action pin (RV6)

- `mergecraft init` scaffolds a consumer-ready workflow (`alexhawat/mergeCraft@v0.1.0a1`, `pull_request` trigger, `models:` list) matching `examples/config.yaml` and Example 1 (RV6)

- ``probe_capabilities`` is ``lru_cache``-backed; ``reset_detection_cache`` clears the probe cache for xdist isolation

- ``detect_sandbox_method`` and ``network_namespace_available`` delegate to the cached capability probe with one unified privilege ladder

- Eval methodology: blocker precision is `None` (unpublished) when a run reports no blockers, and severity accuracy is `None` when there are no locality matches — never a vacuous 1.0

- Landing README redesigned as a REACH-style product page (outline B): problem/solution cards, architecture hero, numbered install, and jump-nav.

- `mergecraft review --help` now states that no flags are required and includes full example commands for local worktrees, GitHub branches, and present or past PRs

- Stale pytest `xfail(strict=False)` markers that were already passing are now real tests; remaining allowed-tree xfails are strict (#276)

- Changed: `gates.terminal_verdict` now defaults to `enforce`; missing terminal verdict reports `inconclusive`. Operators can still set `shadow`

- Changed: `create_pull_request_review` now records through the same validator as `submit_review_verdict`; GitHub posting is an internal publisher, not an agent tool

- The PR integration job runs keyless hermetic integration tests instead of passing on a check that a helper script exists, so a green run means tests executed

- An E2E live slice with no model configured reports `unavailable` in a warning and the step summary instead of a green `skipped`; a configured-but-broken slice still fails

- Live-provider tests report the HTTP status before parsing a response body, and never echo the credential or the request URL; the Nous leg posts the documented default model

- CodeQL results upload to code scanning on the events whose token can write `security-events`, and an analysis failure fails the job; fork and Dependabot pull requests analyse without uploading

- `make workflow-lint` no longer reports success on a host where it could not lint: it fails and says lint is unavailable

- `make docker-build` tags the image with a lowercase repository name, so the target can succeed

- Every runtime dependency is an exact pin, every third-party import in the package is declared, and the declarations nothing imports are gone

### Removed

- The MCP server no longer mounts a webhook endpoint; a signed delivery was verified but processed nothing, and its replay window could never fire.

- Provider circuit-breaker, health, budget and routing-eval helpers that no review path called are removed.

- Four context-retrieval modules no review path imported are removed.

- The unused `get-installation-token/main.py` script; the `get-installation-token` composite Action is unchanged

### Fixed

- The OpenCode harness hands its isolated `XDG_DATA_HOME` tree to the unprivileged agent user before `setpriv` drops privileges.

- An offline review called as a library without a findings file now asks the model for structured findings, as the CLI always does.

- A review whose agent calls `run_analyzers` on a host without a sandbox no longer fails closed with "checkout integrity failure: tree changed during read-only review".

- The Action images ship OpenCode 2.x (`@opencode/cli` 2.0.29) for every model routed through the OpenCode harness (Nous, OpenCode Zen and Go, MiniMax, TokenHub, custom providers).

- The hardened example workflow's approval gate now receives only the review verdict, not the whole evidence packet.

- The Codex reviewer now runs in the repository it reviews. An offline review started from another directory failed at once, because Codex refuses to run outside a git repository.

- The self-review passes each review step's evidence packet to later steps as a file.

- Both Action images replace the brace-expansion and undici copies bundled inside npm with their patched releases, pinned by checksum.

- A self-review re-run on a job token now picks up the earlier run's checkpoint and progress comment.

- `doctor`, `config show` / `config explain` and the config loader now agree on which files contribute.

- `doctor` fails before printing anything when its rendered output would contain a credential value, naming the environment key and never the value.

- Logfire workflow wiring accepts the lowercase `alexhawat/mergecraft@<ref>` spelling the docs print, while still refusing similarly-prefixed forks and an empty ref.

- `watch` and the review comment's run link honour `GITHUB_API_URL` / `GITHUB_SERVER_URL` for GitHub Enterprise hosts.

- The unused hosted-plan residue is gone: the two `AccountPlan` vocabularies, the context `plan` field and the `proxyModel` producers and consumers were removed, none of which had a reader.

- A Review run that records its verdict now publishes exactly one GitHub review from it, with the recorded findings as inline comments.

- An unknown or missing trust tier is treated as `untrusted` everywhere, including a tool context built without one.

- The recorded prompt version now reflects the rendered prompt the reviewer actually received, so two runs configured with different inline budgets record different versions.

- A configured inline budget of `0` is honoured everywhere: the offline analyzer pre-pass, the pipeline fallback and the rendered prompt now agree, instead of the pre-pass silently using the default.

- The review doctrine states the Python 3.11 install floor, and the `push` input, the compatibility matrix and the review checks describe review-only behaviour — no value grants commit or push.

- Documentation links and glossary anchors resolve on GitHub (the glossary's `{#id}` headings become real anchors), and the operator-facing `MERGECRAFT_*` knobs are documented in `docs/cli.md`.

- CI failures with no evidence of cause are now reported as **unattributed** — blocking, with `introduced_by_pr: unknown` — instead of being cleared as not-this-PR.

- `--allow-stub` permits the stub only when the browser stack is unavailable and logs why, instead of bypassing a reachable browser.

- Every agent CLI driver and the OpenCode server boot no longer hang when a child fills its stderr pipe.

- OpenCode server boot no longer blocks the event loop in a blocking `readline`.

- The Claude and Gemini reviewers can no longer write files, run shell tools or fetch the web.

- Tracing no longer clears a bound data-residency allowlist.

- The sticky progress comment keeps the finding ledger and the learnings delta across the final deterministic-record write, so a later run hydrates every prior record instead of losing it.

- Analyzer findings are attributed to the file that actually caused them again.

- GitHub App runs mint separate least-privilege API, Git, and cross-repository tokens. Cleanup attempts to revoke every internally minted token.

- Coverage gates use native line/branch metrics and accept only complete, fingerprinted shard sets. A single run trace covers setup through publication across Action, offline, and MCP execution.

- Evaluation records round-trip without dropping corpus data and write atomically after validation.

- The keyless shadow job is a fixture replay of two hard-coded packets. It does not read a live review and leaves #737 open.

- A live shadow row records the model on the packet (the slug that ran, else the configured reviewer). When the packet has no model, the row leaves it unset instead of claiming Claude.

- `mergecraft eval ingest --from-dismissals` turns recorded dismissal signals into structural eval cases. A dismissal is stored as `agent-seeded`, not as a human label (#738).

- Resetting the MCP shell sandbox cache tolerates a patched capability probe — it clears the probe cache only when a callable `cache_clear` is present — so test-isolation teardown no longer errors.

- `mergecraft verify-behavior` stays inert on a fork or `pull_request_target` Actions event instead of always skipping the trust gate (#61)

- `mergecraft review --verification-report` does not load a report on an untrusted checkout, including when a workflow treats the workspace as trusted (#61)

- Verify criteria are scored per criterion; reproduce matches page text to repro notes; `--start-command` retries navigate while the app comes up (#61)

- Local `--shell enabled` now refuses when no sandbox backend is available unless `MERGECRAFT_ALLOW_UNSANDBOXED_SHELL=1` is set; on macOS, `sandbox-exec` is the backend when present (#593)

- Tracked public markdown is linted for decision-ledger tokens, -dot citations, and pointers into gitignored plans; Priority 1 docs were rewritten to stand alone (#709)

- `trivy` on Apple Silicon provisions the native ARM64 build so the local coverage gate does not hang under Rosetta

- Action reviews no longer crash at startup with `infra_error` when loading the shared token cap (#741)

- Enabled Jev reviews now keep the shadow-judge record next to the evidence packet after the command finishes, so paid calibration rows are retrievable (#728)

- A TypeSafe connect, DNS, or timeout failure on the shadow judge records a skip and leaves the completed review successful (#728)

- `jev.model` accepts only the pinned `jev-1.13.0` id, so a configured newer version cannot run while audit rows still claim the pin (#728)

- The Action-pin staleness budget counts changes rather than landings.

- A stale self-review Action pin on `main` no longer fails every open pull request.

- The sticky run record lists Action pin (manifest C) next to baked image source (S) so pin-lag (pinning S deploys the previous digest) is visible without reading Action logs (#641)

- Consolidated integration CI retains Python 3.11 and 3.14 coverage after prerelease/main reconciliation; the coverage ratchet runs once on 3.14.

- Bring the GitLab review-support matrix correction from main to the prerelease branch.

- Local base-only reviews retain working-tree changes; remote comparisons deepen bounded shared history and fail explicitly rather than substitute endpoint diffs.

- Installed convergence evaluations include their recall corpus. Example drift checks run in disposable copies and no longer rewrite tracked outputs.

- Redaction preserves closing assignment brackets and ordinary source paths while retaining secret-pattern and high-entropy controls.

- Optional image live checks require an actual terminal review rather than CLI help.

- Self-review App tokens now refresh per provider attempt and revoke after the job.

- Action images use patched, checksum-pinned npm and GitHub CLI tooling and remove unused vulnerable pip bootstrap copies.

- Local review honors configured model chains, explicit/environment precedence, fallback restrictions, and cumulative budgets; a process without a terminal verdict is inconclusive (#592).

- Installed skills use a verified documentation commit containing every linked target and teach canonical, explicitly scoped provider authentication (#589).

- Analyzer isolation reports unsupported macOS accurately and warns when trusted execution lacks isolation.

- Credential broker stream failures now close the connection without inserting a second HTTP response, and client disconnects release upstream responses (#595)

- Brokered Codex runs preserve configured proxy bypass entries and always bypass proxies for the loopback broker, without changing parent proxy settings (#597)

- Removed an obsolete Codex broker auth branch that suppressed the API-key authentication diagnostic; subscription authentication is unchanged (#596)

- Release verification uses compatible GitHub CLI policy flags, validates deployment candidates automatically, and publishes canonical image tags only after signed staging digests verify.

- Release E2E now runs for reusable workflow callers, and image promotion requires verified signatures, source provenance, and SBOM attestations.

- Logfire `llm.call` rows now include the prompt mergeCraft sent and the model output, with a real duration instead of an empty ~2µs span

- Codex, Claude, and Gemini tool-use now shows up as `tool.call` children on the same Logfire trace as the review run

- Authentication quick start uses registry labels (`anthropic`, `openai`, `google`) instead of harness names that `provider auth` rejects (#590)

- GitHub Action Logfire tracing honors `MERGECRAFT_TRACING_REGION`, so an EU write token is no longer posted to the US ingest host (#607)

- Anchor-422 recovery no longer spins on an out-of-range comment index — it demotes all inline comments and posts once (#570)

- The published GitHub review body always matches the terminal submission; probe strings and split publication races no longer land a placeholder review (#572)

- Multi-reviewer findings carry server-stamped `raised_by` attribution on the published review; agents cannot supply the field via `submit_review_verdict` (#574)

- Token spend slightly over `runBounds.tokenBudget` warns and completes instead of failing at the cliff; crossing the hard ceiling still ends the run (#571)

- Base-branch coverage measurement reads that worktree's `.mergecraft/config.yaml` instead of the PR head's — a PR that adds a config key and its schema field no longer fails the base run (#573)

- A refused terminal verdict now reaches the deterministic run record by name.

- Git MCP containment: refuse `--no-index`, confine positional paths, deny credential paths (`.git/config`, askpass tree), and redact git failure text before it becomes a tool result

- Post-run retry loop classifies scope and policy refusals before resuming — deterministic refusals no longer spend a second provider turn

- Single Loguru writer with `enqueue=True` and explicit queue drain — runner logs no longer interleave mid-line from concurrent stdout/stderr writers

- Bubblewrap namespace failures surface `user_namespace_failure_hint` once per run (not gated behind a non-zero Codex exit code)

- `checkov` and `yamllint` catalog rows document linux-amd64 manifest-only provisioning instead of presenting as runtime failures

- Git config MCP: deny `config --list` and credential-bearing keys on `config --get-all` so brokered auth headers cannot leak through enumeration

- `get_commit_info` validates unified diff evidence before establishing review scope; successful `checkout_pr` records scope via `register_review_scope`

- Claude driver: pass ``--verbose`` alongside ``--print --output-format=stream-json``.

- Trajectory auditor classifies tool failures before counting them, so self-corrected schema slips, policy refusals, and environment faults no longer masquerade as ignored errors that block the PR

- Codex fallback routing reads `decision.verdict` from the in-process evidence packet instead of racing the check-runs API

- Pipeline predicate validation no longer rejects repository paths whose names contain substrings such as ``subprocess`` or ``import``; the closed regex is the sole control

- Pipeline severity predicates include ``Trivial`` and rank unknown severities below every taxonomy member instead of treating them as ``Minor``

- ``ReviewEngine.run`` clears the timeout callback on every invocation so a second run with ``on_timeout=None`` does not retain the first run's handler

- Required static checks block approval unless every row is explicitly ``passed`` or ``not_applicable``; ``unavailable``, ``error``, ``timeout``, and unknown statuses no longer satisfy the gate

- Review publication reads repo settings from the run-scope snapshot taken before untrusted execution instead of reloading ``.mergecraft/config.yaml`` from the mutable checkout

- Shipped ``operational_readiness`` policy pack rules now declare the required evidence keys ``enforcement: required`` consults before it treats the rule as satisfied

- Authenticated git operations against GitHub now work at all.

- `actions/checkout` no longer persists its token in the review workflow, the shipped hardened example, its template, or the dogfood artifact.

- ``prep`` lockfile selection prefers ``uv.lock`` over a stray ``requirements.txt``; ``should_run`` threads one ``cwd`` into ``run`` instead of reading ``Path.cwd`` twice

- The Action image now installs the `[tracing]` extra (`uv sync --frozen --no-dev --extra tracing`).

- `mergecraft.yml` now actually passes the tracing inputs it has supported since.

- ``redact_tool_payload`` caps UTF-8 byte length (not Python character count) and keeps a head slice plus a visible truncation marker instead of discarding the whole body

- ``redact_url`` preserves ``http`` vs ``https`` when redacting basic-auth userinfo

- ``tests/tracing/test_redaction_doctests.py`` executes ``mergecraft.tracing.redaction`` doctests

- Webhook signature verification encodes signature operands with UTF-8 surrogateescape before ``compare_digest``, so non-ASCII header bytes are rejected instead of raising ``TypeError``

- The MCP server no longer mounts a webhook endpoint: a signed delivery was verified but processed nothing

- `validate_http_url` rejects whitespace and control characters anywhere in a provider URL, not just at the ends.

- `mergecraft workflow` resolves a relative `--workflow` against `--cwd` on every subcommand.

- The consumer workflow file is replaced atomically by `mergecraft workflow`, matching the config writer. A crash mid-write used to leave it truncated

- `provider migrate` validates a migrated `NOUS_BASE_URL` through `validate_http_url` like every other URL entry point, instead of storing it unchecked

- `.mergecraft/config.yaml` is replaced atomically (temporary file plus rename, preserving permissions) by every CLI writer.

- `mergecraft workflow provider add --apply` writes the registry config only after the workflow file lands, and rolls the workflow back if that config write then fails.

- `mergecraft workflow provider add --url` on an already-registered provider now applies the validated endpoint to the row that is wired and persisted.

- Indexed registry credentials survive the legacy credential re-injection in `build_agent_env`.

- `list_check_runs` omits `check_runs` when the listing is truncated, instead of returning a partial catalog with `total_count`.

- Check-suite log fetch skips with a distinct unavailable payload when no GitHub client is bound, instead of looking like “no failed runs”

- Catalog-check rejects all-zero `sha256` provenance pins (placeholders that made `provision_managed_binary` treat a trailing-slash URL as a directory and fail with `Is a directory`).

- A transient Nous HTTP 404 (including a false billing/credits refusal) now fails over to the next model instead of stopping the run and reporting a missing `set_output` schema failure (#466)

- The approval gate now unions agent findings with analyzer findings, so an agent Critical or Major finding fails ``mergecraft-approval`` and the evidence packet's ``request_changes`` action.

- A clean mypy JSON typecheck no longer fails the SARIF convert step, so the mypy artifact still uploads for review evidence

- Evidence packet `decision.verdict` is a GitHub check conclusion (`success` / `failure` / `neutral`); schema version 1.9.0

- `mergecraft-approval` posts `neutral` when the evidence packet was not assembled, instead of omitting the check

- Custom provider slugs not in the operator registry now fail closed instead of silently routing to OpenCode; the built-in catalog allow-list was narrowed accordingly.

- Repo-native analyzers no longer fall back to an arbitrary PATH binary.

- An explicit `--model` now beats `MERGECRAFT_MODEL`.

- Offline reviews (`--base`/`--head`, `--diff`, `--cwd`) can record a terminal verdict.

- Retryability now has one decision path.

- Codex `error` and `turn.failed` events are no longer discarded.

- Provider quota exhaustion is now classified as retryable for failover.

- `opencode serve` output is now drained for the process lifetime.

- A provider timeout no longer kills the review.

- `mergecraft --version` reported `0.1.0` while the project was at `0.1.0a1`: the number was restated as a literal in `mergecraft/__init__.py` alongside `pyproject.toml` and the two drifted.

- `review --dry-run` skips the analyzer catalog while still materializing the diff and returning the review prompt (#401)

- `load_audit_events` skips malformed JSONL lines and non-dict payloads instead of raising (#398)

- `route_model` routes security specialist at `critical` risk to the same capable model as `high` instead of Haiku (#394)

- Checkout and packaged `defaults.yaml` copies drifted after README v2; `make pins-check` gates byte identity (#402, #414)

- Hermes generated skill package lists `GEMINI_API_KEY` and `NOUS_API_KEY` (not `GOOGLE_API_KEY`) in `required_environment_variables`, matching `docs/authentication.md` (#415)

- Coverage ratchet floor raised to 80% after new docs contract tests increased measured line coverage above the prior ceiling

- Transitive `h2` 4.4.0→4.4.1 in `uv.lock` for `pip-audit` (PYSEC-2026-3628)

- `mergecraft init` no longer emits `uses:./` in consumer repos — published Action ref instead (V8/)

- `mergecraft init` scaffold drops comment triggers and unsafe `github.event.comment.body` prompt wiring; defaults to `CLAUDE_CODE_OAUTH_TOKEN` (README Example 1 parity)

- Evidence image uploads, issue comments, and PR label tools work on review-only runs again

- Linked-repo contract breakage is included in ordinary PR checkout, not only `mergecraft xrepo explain`

- Linked-repo checkout reads only operator-granted siblings, and skips a sibling whose HEAD is not the pinned SHA

- Webhook signature verification fails closed without a configured secret

- Untrusted download and clone URLs are SSRF-checked, and binary downloads pin DNS to the validated addresses

- `bandit` now uses built-in `--format json` instead of the optional SARIF extra, so auto-enabled Python security coverage still runs on plain Bandit

- `bundler-audit` now runs the gem CLI (`bundler-audit check --format json`) instead of `bundle audit`, so Ruby lockfile audits actually execute

- `tflint` no longer passes changed `.tf` files as positional args (invalid since TFLint 0.47); it lints the working directory and the pipeline still scopes findings to the diff

- `bundler-audit`, `cargo-audit`, and `cargo-deny` findings no longer fake a line-1 GitHub anchor when the tool did not report a line; crate/gem coordinates stay in the message

- `clippy` now runs as `cargo clippy --message-format=json` (package/workspace) instead of passing PR paths as cargo args, so auto-enabled Clippy keeps rustc JSON findings

- A successful analyzer with empty stdout (for example a clean `tsc --noEmit`) is treated as passed instead of unavailable

- `tsc` project-level diagnostics without a file location (for example `error TS18003`) now surface as body-only findings instead of a silent pass

- `tsc` help text and other unmatched nonempty stdout now fail closed instead of counting as a clean pass

- Project-level `tsc` findings survive diff scoping when the PR only changes `.ts` / `.tsx` files

- `brakeman`: command changed from `-o brakeman.sarif` (writes to file) to `-o -` (stdout) so the SARIF output is captured by the adapter; `parser: sarif` is unchanged (Thermos Finding 1, #338)

- MCP HTTP server now issues a separate bearer token for the orchestrator ``/mcp`` route; reviewer/verifier harnesses keep ``ToolContext.mcp_auth_token`` for their role endpoints (#349)

- OpenCode HTTP ``llm.call`` usage attrs omit unset counters instead of zero-filling ``gen_ai.usage.*`` when the session response reports output tokens only (#297)

- `agents/claude`: `write_mcp_config` wrote a single MCP server entry pointing to `/mcp/reviewer` (derived from the orchestrator's `current_agent_id` at `_run` start).

- `mcp/git`: corrected `commit_changes` tool description — it performs a local commit only and does not push to the remote or produce a GitHub-verified commit (#259)

- `mcp/git`: `--namespace` is now refused outright rather than forwarded.

- Fixed eval corpus run directories splitting on slashes in model slugs (e.g. `openrouter/openai/gpt-5`) — run ids are sanitized to a single flat component (#219)

- Fixed live corpus reviews running in an empty scratch directory — the case's repo context is materialized before the review (#220)

- Benchmark result sets now record full version pins and a reproducibility digest, so same-commit runs are comparable (#140)

- Two ensemble models that both report no findings no longer escalate to a judge (#238)

- Reviews of Python repositories with `shell: disabled` no longer fail closed after a completed review just because dependency installation was skipped as a security policy

- Fixed: model-chain fallback now advances when the provider succeeds without a terminal verdict; a valid `request_changes` is a usable result and does not trigger fallback

- Fixed: explicit `harness:` now selects the runtime agent, not only span labels

- Fixed: a previously recorded `approve` is re-validated before GitHub publish, so a later confirmed blocker cannot ship an `APPROVE` review

- Fixed: body-only `create_pull_request_review` with `approved: false` no longer posts a GitHub `APPROVE`

- Fixed: `create_pull_request_review` now requires established review scope in Review modes, matching `submit_review_verdict`

- Fixed: terminal-verdict shadow mode now records a predicted outcome beside the legacy result on the live finalize path

- Fixed: a body-only COMMENT is no longer recorded as `request_changes`, and body-only `request_changes` is rejected unless it has real findings

- Fixed: publication must match the recorded terminal verdict and is re-validated before sending `APPROVE`

- Fixed: IncrementalReview `report_progress` no longer advances the model chain

- Fixed: Review completion via `create_pull_request_review` now records a terminal verdict, and IncrementalReview may complete via `report_progress` without mapping to `inconclusive`

- Fixed: verifier confirms persist outside replaceable analyzer run state, including agent-authored findings

- Fixed: a verifier `confirm` now persists the finding fingerprint so `approve` over a confirmed blocker is rejected on the live tool path, not only in unit tests that seed `verified_ids`

- Fixed: a stored `approve` is re-validated at finalize against current evidence, so a later failed required gate or verifier confirm cannot leave the run `passed`

- Fixed: a provider success without a usable terminal verdict now advances the model chain when fallback is allowed, instead of accepting the first process-successful result

- Fixed: a later `run_static_checks` call that matches no gates no longer wipes a prior failed row, so `approve` still fails closed

- Fixed: `approve` is now rejected on the live path when `run_static_checks` recorded a failed required gate; previously the validator only saw those rows in unit tests

- Fixed: a review run that completes without submitting a terminal verdict now reports `inconclusive` (a `neutral` check conclusion) instead of `passed`.

- The checkout tool refuses a pull request number other than the one the run was bound to, and refuses a fork pull request on a run trusted for execution or authority.

- The `MERGECRAFT_DISABLE_SECURITY_INSTRUCTIONS` environment switch is removed; the security paragraph is always in the system prompt.

- Inside GitHub Actions the CLI no longer loads a `.env` from the checked-out workspace at startup; set `MERGECRAFT_ENV` to load an explicit file. Local (non-Actions) runs are unchanged.

- Linked-repo grants now match an exact lowercase `owner/name`; a bare name no longer authorizes a same-named repository, and two manifest entries sharing a name are both refused.

- Harbor's agent wrapper invokes `mergecraft review` instead of the deprecated `diff-review` alias.

- The sandbox write/network test and the symlink-target chown test run in the privileged lanes built for them, and fail rather than skip inside those lanes

- The keyless provider-catalog smoke no longer hides behind a live gate and runs in the unit suite

- Both in-image test scripts pin the same `pytest` and `pytest-asyncio` as the project they test

### Security

- The Claude reviewer can no longer read the run's credential material.

- The review job declares `actions: read`, and no review rung falls back to the shared `github-actions[bot]` login when no reviewer App is configured.

- Untrusted static checks run inside the sandbox against a disposable copy-on-write view of the checkout.

- Local log sinks are scanned for credentials after the run.

- Transitive `soupsieve` 2.8.4→2.9.2 in `uv.lock` for `pip-audit` (CVE-2026-85999, CVE-2026-86000) (#728)

- Fork-controlled `.mergecraft/config.yaml` can no longer lift the untrusted tracing-content cap; export of prompt bodies on fork PRs requires the Action input, env, or trusted base settings

- MCP HTTP startup no longer treats a TCP connect probe as proof of identity; server-thread failures propagate and ``GET /health`` requires a per-run nonce

- Analyzer JSON and JSONL outputs are structurally redacted by key and value before persist, so non-prefixed secrets in trufflehog-style payloads do not reach prompts or ``.mergecraft/analyzer-runs/``

- Entropy-based secret redaction uses a length-relative threshold with benign-shape exclusions for git SHAs, hex runs, and identifiers so legitimate code tokens in logs are not mangled unnecessarily

- OpenCode review sessions deny ``webfetch``, ``external_directory``, and ``edit``; ``read`` is allowlisted to the checkout and evidence scratch instead of ``*``

- Post-run checkout integrity verification via ``security.review_integrity`` hashes the tree before review and fails closed on mutation

- ``setpriv`` argv carries ``--no-new-privs``, ``--inh-caps=-all``, and ``--bounding-set=-all``; fails closed when ``setpriv`` lacks ``--bounding-set`` support

- Root-side ``git`` subprocesses route through ``utils/git_hardening.git_argv`` with pinned safe-config keys; ``make lint`` enforces the route via ``scripts/check_git_argv.py``

- ``prepare_workspace_for_agent`` no longer recursively chowns ``.git``; sandbox shell binds every registered workspace root's ``.git`` read-only

- Linked-repo ``_rev_parse_commit`` rejects leading-dash revs, validates pinned SHA shape, and passes ``--end-of-options`` before the rev

- Sandbox capability probes run real isolation checks instead of gating on ``CI``; untrusted MCP shell refuses unsandboxed spawn unless ``MERGECRAFT_ALLOW_UNSANDBOXED_SHELL=1``

- Skipped untrusted analyzers emit a ``Minor`` finding (``rule_id: analyzers.sandbox-unavailable``) naming missing isolation primitives

- ``sudo-unshare`` shell spawn passes env by name via ``--preserve-env`` with ``env=env`` on ``Popen`` so provider keys never appear in argv

- Namespaced shell spawn hides every ``git`` binary and binds ``.git`` read-only inside ``unshare`` / ``sudo-unshare`` branches; unsandboxed opt-in runs the raw command without host mount soup

- Python ``prep`` installs into ``.mergecraft/prep-scratch/prep-venv`` with a default-deny env allowlist so PR build deps cannot mutate the reviewer's interpreter or inherit provider credentials

- Mutating MCP tools other than review-session verbs (`select_mode`, checkout, review publication) are refused unless a write-capable mode is selected, including before mode selection (#350)

- GitLab webhook `X-Gitlab-Token` is compared as a shared secret, not an HMAC of the body (#361)

- External URL retrieval also blocks decimal, hex, and short IPv4 forms, IPv6-mapped loopback, and DNS that resolves to loopback, link-local, or metadata; DNS failure is fail-closed (#362)

- Dependency and container-image vulnerability gates no longer report a pass without running a scanner (#362)

- Untrusted PR trees no longer receive a `shell` tool when PID-namespace isolation is unavailable (#287)

- Untrusted PR trees no longer run package install lifecycle scripts in the Action process when `shell` is the default `restricted` (#284)

- `mcp/git`: the glued single-token spelling (`-ckey=value`) is refused alongside the spaced and inline forms, so the alias-execution block no longer depends on how the flag was written.

- `mcp/git`: `git diff --output=<path>` wrote an arbitrary file through a read-only tool — the subcommand allowlist constrains the verb, not the flags the verb accepts.

- `mcp/git`: `-C`, `--git-dir`, and `--work-tree` are now confined to the resolved primary repo root; any path outside raises `ValueError` with the offending path in the message (#257)

- Linked-repo reads are grant-gated: a run can only load repos declared in its authorized set; linked-repo and ticket text render through the fence as untrusted data

- CLI offline reviews now derive a trust tier from review-source provenance; cloned or out-of-root paths review at untrusted tier unless the operator passes an explicit `--trust` override

- Executable repo config (`setupScript`, `prepushScript`, `stopScript`, `staticChecks[].command`) from an untrusted review source is ignored; declarative config still applies

- `build_mcp_app_for_role` with `role="reviewer"` or `role="verifier"` no longer mounts the orchestrator toolset at `/mcp`; only the role-specific path is active (#282)

- The changelog-preview workflow passes no repository secrets to the third-party reusable workflow it calls

- Cleanup and token-revocation failures are logged as warnings naming the step and path — including a residual askpass file — instead of being suppressed.

## [0.1.0] — 2026-08-14

> **Never published.** `0.1.0` was never tagged, has no GitHub release and no
> package upload; its entries are kept here as history. The version above,
> `0.1.0a3`, is the pre-release cut in its place. `0.1.0a1` (`521c0aed`) was an
> Action-only tag — no PyPI upload and no GitHub release; `0.1.0a2` was skipped.
> A consumer upgrading from `v0.1.0a1` should read the **Breaking — action
> required** block above.

Planned initial public release (never published): mergeCraft is a standalone,
BYOK GitHub Action for AI-powered PR review — no proprietary backend, no
account, review runs against your own Claude/Codex/Gemini subscription or API
key.

Full pre-release development history: see
[`docs/dev/changelog-archive.md`](docs/dev/changelog-archive.md).

### Added

- Multi-agent review drivers for Claude Code, Codex, Gemini CLI, Cursor
  Cloud, and OpenCode, each resolving from a subscription login or an API
  key with no proprietary backend in between
- Curated multi-provider catalog (Nous Research/DeepSeek, Tencent TokenHub,
  MiniMax) plus a generic custom OpenAI-compatible gateway, configurable via
  `.mergecraft/config.yaml` or `with:` inputs
- Ordered model chain with automatic fallback: entries missing credentials
  are skipped and retryable provider failures advance to the next entry
- Analyzer catalog covering linters and type-checkers (Ruff, MyPy, Pyright,
  ESLint, Biome, Oxlint), dependency and secret scanning (OSV-Scanner,
  Trivy, TruffleHog), pattern scanning (Semgrep/OpenGrep/ast-grep), contract
  diffing (oasdiff, Squawk, buf), GitHub-native tools (actionlint, zizmor,
  ShellCheck, Hadolint), and a first-party scanner for MCP/skill manifests;
  selection is trust-tier aware (`analyzers: off|auto|full|untrusted-only`)
- Merge Evidence Packet: every run emits a versioned, structured record of
  findings, analyzer checks, the blast-radius lane, and the structural
  decision, exposed as the Action's `evidence_packet` output
- Blast-radius classifier maps changed paths to low/medium/high merge
  lanes, with additive per-category repo overrides
- Structural `mergecraft-approval` status check — a pure function of typed
  findings, run completion, and trust tier, so a crashed or timed-out run
  reports `neutral` rather than silently passing
- Eight trajectory checks read the agent's own mediated tool calls (a file
  edited but never read, a tool error retried with nothing changed, and six
  more) and feed the evidence packet
- File-backed eval bank (`mergecraft eval add|list|replay|promote`) turns
  real review outcomes into regression cases and permanent pytest tests
- Optional tracing: a local JSONL sink plus Logfire/OTLP remote export, a
  full per-run span tree, and a redaction boundary that scrubs secrets
  before any sink sees them (`mergecraft tracing`, `mergecraft auth logfire`)
- `mergecraft findings export|carryover` files GitHub issues for review
  findings a merged PR left unresolved, so they survive past the merge
- Optional GitHub code-scanning upload (SARIF) for analyzer findings
  (`sarif_upload: enabled`)
- Per-run nonce fencing neutralizes prompt-injection attempts in untrusted
  PR titles, bodies, and comments before they reach the reviewing agent
- Comment-triggered runs (`@mergecraft`) are gated on the commenter's GitHub
  author association by default, extendable via `commentInvocationAllowlist`
- CI pipeline intelligence clusters failures, distinguishes flaky and
  pre-existing failures from ones the PR introduced, and blames failures to
  the hunks that caused them
- `mergecraft models|analyzers|eval|tracing|learnings|auth` CLI command
  groups; README's Action-input, Action-output, and CLI reference tables are
  generated from the live sources and CI-gated against drift
- Hardened example workflow
  (`examples/workflows/mergecraft-hardened.yml`) with a same-repo secret
  guard, wait-for-CI, and approval-check enforcement
- Release pipeline builds each image once, attaches SBOM and vulnerability
  scan reports, cosign-signs and attests the digests, then promotes tags by
  digest — no second rebuild between scan and release

### Changed

- Typed `ProviderConfig` for OpenAI-compatible gateways (capabilities declarative; API keys stay in env vars). No wire-format change to generated `opencode.json`
- **BREAKING** — `with: model:` is now the head of the effective model
  chain rather than a replacement for it; set `model_pin: enabled` (or
  `modelPin: true`) to restore the old single-model behavior
- **BREAKING** — comment-driven invocation under `pull_request_target` is
  refused by default; opt in with `allow_pr_target_comments: true`
- **BREAKING** — new learning entries land in a quarantined staging section
  by default instead of taking effect immediately; set
  `autopromoteLearnings: true` to restore auto-promotion
- **BREAKING** — an unrecognized `analyzers:` input value now resolves to
  the strictest tier (`untrusted-only`) instead of the most permissive
  (`auto`)

### Security

- Agent privilege drop fails closed: a run that cannot drop root aborts
  instead of continuing to execute the reviewing agent as root
- Trust tier is derived before any repo-controlled script or git setup
  runs, and an unrecognized event shape fails closed to `untrusted`
- Agent CLI subprocesses receive an explicit credential allowlist — no
  ambient GitHub tokens or inactive provider keys reach the process
- A first-party analyzer (`agentsec`) scans `.mcp.json`, `CLAUDE.md`,
  `AGENTS.md`, and skill files for policy violations, and still runs under
  `shell: disabled`
