# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- CI SARIF from ruff, mypy, and bandit is review evidence: `error` keeps
  Major/Critical (not clamped to Minor); a listing error on one workflow run
  does not skip later runs; a Major/Critical finding is kept over a less
  severe duplicate fingerprint. Dogfood `.mergecraft/config.yaml` lists those
  three `ciEvidence.sarifArtifacts`, and `.github/workflows/ci.yml` uploads
  them. A ruff SARIF error can fail `mergecraft-approval` (#464)
- `make action-pin-check` also measures the pin against the default branch's own
  tip, not just against the other branch's pin. Comparing pins to each other
  passes when both are equally stale, which is what happened after #457 merged:
  both branches pinned the same SHA and the check reported OK while the reviewer
  ran none of the fixes that had just landed. Lag is counted over
  `src/mergecraft/` only, since docs and test commits do not change what the
  reviewer executes (#450)
- `make action-pin-check` guards the self-review Action pin against drift.
  Because `.github/workflows/mergecraft.yml` runs on `pull_request_target`,
  GitHub resolves its `uses:` pin from the **default branch**, so a fix merged
  to `pre-0.0.1` does not reach the reviewer until it reaches `main` — a skew
  that reached 687 commits undetected and made PR #443 time out on a ceiling
  already fixed on the branch. The check also rejects a one-sided bump that
  leaves the review and fallback steps on different SHAs. Advisory in CI: a
  stale pin is a property of the default branch, not of the PR under review
  (#450)
- First-pass recall metric (`mergecraft eval convergence`, `make eval-convergence`) with multi-round bank cases and a paired regression gate that holds first-pass recall flat while the DG1 precision corpus stays at or above its floor
- Open-PR finding ledger in the sticky progress comment — `mergecraft findings ledger --pr N` inspects inline, deferred, withdrawn, and unpublished fingerprints without filing GitHub issues (D4, D5)
- Optional recall pass (`review.recallPass`, default off) dispatches `mergecraft-recall` after aggregation; novel findings always publish in the deferred lane (D1, D7)
- Optional round-aware budgets (`review.roundBudgets`) scale token, cost, tool-call, and subagent ceilings by review round; defaults stay flat until opted in (RC12)
- Lens execution recording on `ToolState`, review metadata, and merge-evidence packets; findings may carry optional `lens` attribution (D9)
- Collateral lists on `Critical` and `Major` findings name callers, tests, and other files that must move with the fix; inline comments render them under **Also update:** (RC11)
- Incremental reviews promote deferred findings when their cited path intersects the incremental diff, bias complement lens routing toward lenses that did not run last round, and label first-pass misses on unchanged lines honestly (RC9, D10)
- Opt-in `antislop` analyzer: YAML rule pack for placeholder code, narrator comments,
  swallowed errors, pass-through wrappers, phantom imports, and related low-quality patterns
  on changed Python and JS/TS files (#393)
- Append-only enterprise audit producer for ``.mergecraft/audit.jsonl`` via
  ``append_audit_event`` and ``record_blocking_decision``; blocking terminal
  verdicts now persist audit events consumable by ``mergecraft audit export``
  (#417)
- `make lint` checks that jobs calling local reusable workflows grant at least the
  permissions the callee declares, catching ``startup_failure`` permission mismatches
  at authoring time (#425)
- Integration PR coverage now measures ``refs/pull/N/merge`` and reports delta vs the
  base branch via ``scripts/check_coverage_delta.py``, distinguishing inherited floor
  breaches from regressions caused by the PR (#432)

### Changed

- Overflow agent findings now append to a server-written `### 🗂 Deferred findings` section with full finding text (non-blocking); analyzer overflow remains in `### 🔧 Mechanical findings` (RC1, RC2)
- `review.verificationBudget` (default 24; `0` = no cap) caps verifier dispatches independently of `analyzers.inlineBudget` (RC3, D2)
- Harbor `MergecraftReviewAgent` resolves the default `uv tool install` ref lazily in
  `install()` via `action_pin_minimal()` instead of calling it at module import (#403)
- Landing README promoted from `readme_test.md` draft: agent-first layout, glossary links,
  auth table with recommended models, CLI how-it-works section, and `v0.1.0a1` Action pin (RV6)
- `mergecraft init` scaffolds a consumer-ready workflow (`alexhawat/mergeCraft@v0.1.0a1`,
  `pull_request` trigger, `models:` list) matching `examples/config.yaml` and Example 1 (RV6)

### Fixed

- `validate_http_url` rejects whitespace and control characters anywhere in a
  provider URL, not just at the ends. A stored URL is written verbatim into the
  consumer workflow YAML, so an interior newline could open a new key or step
  there. `workflow provider add` also re-validates a stored row before wiring it
- `mergecraft workflow` resolves a relative `--workflow` against `--cwd` on every
  subcommand. The registry config was scoped by `--cwd` while the workflow path
  stayed against the process working directory, so invoking from outside the
  target repository could read config from one repo and rewrite another repo's
  workflow
- `mergecraft workflow provider add --apply` writes the registry config only
  after the workflow file lands, and rolls the workflow back if that config
  write then fails. Either half failing used to exit nonzero with config on one
  endpoint and Actions on the other
- `mergecraft workflow provider add --url` on an already-registered provider now
  applies the validated endpoint to the row that is wired and persisted. The
  override was validated and then discarded, leaving the workflow on the
  superseded endpoint with no indication the flag was ignored
- Indexed registry credentials survive the legacy credential re-injection in
  `build_agent_env`. When an `LLM_PROVIDER_<N>_*` secret and its deprecated
  counterpart were both set, the legacy value overwrote the registry one for
  API keys, Claude Code OAuth tokens, and the Bedrock/Vertex chains, inverting
  the documented precedence
- `list_check_runs` omits `check_runs` when the listing is truncated, instead
  of returning a partial catalog with `total_count`. Analyzer JSON arrays no
  longer treat a leading `{"error": ...}` then `[]` as a clean scan
- Check-suite log fetch skips with a distinct unavailable payload when no
  GitHub client is bound, instead of looking like “no failed runs”
- Catalog-check rejects all-zero `sha256` provenance pins (placeholders that
  made `provision_managed_binary` treat a trailing-slash URL as a directory and
  fail with `Is a directory`). Pip-style tools such as `checkov` and `yamllint`
  now ship `provenance: {}` like `semgrep`; a trailing-slash URL is refused
  with a `ProvisionError` that names the URL (#458)
- Empty Bandit JSON stdout is a clean scan (zero findings) instead of a skip;
  non-object `results` rows fail parse the same way as the SARIF converter;
  unparsable stdout still skips without embedding a raw stdout snippet (#467)
- A transient Nous HTTP 404 (including a false billing/credits refusal) now
  fails over to the next model instead of stopping the run and reporting a
  missing `set_output` schema failure (#466)
- The approval gate now unions agent findings with analyzer findings, so an
  agent Critical or Major finding fails ``mergecraft-approval`` and the
  evidence packet's ``request_changes`` action. An empty finding list still
  stays ``neutral``; untrusted runs still never ``success`` (#460)
- Coverage already below `fail_under` on the base branch stays inherited
  drift even if HEAD drops further; a drop of 1.0pp or more below the floor
  when the base is already at the floor is also inherited, instead of always
  treating `head < base` as caused by the PR (#485)
- A clean mypy JSON typecheck no longer fails the SARIF convert step, so the
  mypy artifact still uploads for review evidence
- Evidence packet `decision.verdict` is a GitHub check conclusion
  (`success` / `failure` / `neutral`); schema version 1.9.0
- `mergecraft-approval` posts `neutral` when the evidence packet was not
  assembled, instead of omitting the check
- Custom provider slugs not in the operator registry now fail closed instead of silently routing to OpenCode; the built-in catalog allow-list was narrowed accordingly.
- Seeded ``tokenhub``/``minimax`` registry rows no longer shadow legacy ``TOKENHUB_API_KEY`` / ``MERGECRAFT_CUSTOM_PROVIDER_API_KEY`` credentials: ``resolve_runtime_agent`` honours the same legacy fallbacks as ``has_credentials_for_slug``, and ``provider migrate`` can index those keys.
- Repo-native analyzers no longer fall back to an arbitrary PATH binary. When
  the checkout did not provide a tool, resolution fell through to
  `shutil.which`, so a system copy ran against the consumer's code at an
  unpinned version of unverified provenance — Homebrew's `markdownlint`
  locally, `/usr/local/bin/tsc` on a GitHub runner, which is why `tsc` resolved
  instead of skipping. The six tools installed into the checkout
  (`markdownlint`, `jscpd`, `tsc`, `knip`, `vulture`, `typos`) are now
  repo-local only and skip when absent. Toolchain binaries with no repo-local
  install convention (`cargo` for clippy, `go` for govulncheck) are unaffected
  (#427)
- mergeCraft's consumer workflow approval gate now runs in a separate job that
  `needs:` the review-attempts job, so Codex fallback can post `mergecraft-approval`
  before the fail-closed gate samples check-runs (#433)
- An explicit `--model` now beats `MERGECRAFT_MODEL`. `resolve_model()` read the env override first and
  returned before it ever looked at the flag, so a review asked for one model and ran another with no line
  saying the request was dropped — inverting the repo's own `ConfigLayer` order (CLI > env > YAML > default)
  and the flag's help text. The named model also heads the subagent chains the harness renders, so it
  reaches the whole run rather than just the top-level dispatch, and `config explain model` now reports the
  YAML layer as the config file alone instead of the env value promoted to its front (#468)
- Offline reviews (`--base`/`--head`, `--diff`, `--cwd`) can record a terminal verdict. Review scope was
  only ever established by `checkout_pr`, which an offline run has no PR for, so `submit_review_verdict` was
  refused on every attempt and a completed review — analyzer findings and all — was never decided. The
  materialized diff now establishes scope on the offline path. The post-run retry loop also stops when a
  resume leaves the identical issue set, instead of replaying a precondition that cannot change between
  attempts (#470)
- Retryability now has one decision path. `_is_retryable_failure` gated on `metadata["retryable"]` alone
  while `_retryable_failure_reason` inferred the same property from the error text, and only the
  metadata-blind one decided — so a driver that omitted the flag was silently read as "permanent" and its
  failure terminated the run. An explicit flag still wins in both directions; an omitted one now falls back
  to inference. A retryable failure at the chain tail is bounded to one in-place retry and then returns that
  failure, instead of re-asking a refusing provider until the attempt cap raised and replaced the real error
  with a cap message (#447)
- Codex `error` and `turn.failed` events are no longer discarded. Codex reports fatal failures as structured
  events on stdout, and the stream handler had no branch for them, so the message was counted and dropped
  and the run reported whatever unrelated text stderr happened to hold — PR #443 surfaced "Reading
  additional input from stdin..." for a quota exhaustion, in the job annotation, the merge evidence packet,
  and the chain log. The provider's own message is now the run's error and feeds retry classification (#445)
- Provider quota exhaustion is now classified as retryable for failover. The CLI classifier matched only
  rate-limit wording (`rate limit`, `too many requests`, `overloaded`, `429`), so Codex's "You've hit your
  usage limit" matched nothing and read as permanent — the chain refused to try the next model even though
  the next model was unaffected (#446)
- `opencode serve` output is now drained for the process lifetime. Boot read the child's stdout only until
  the listening URL appeared and nothing read either pipe afterwards, so once the child filled the ~64KB
  pipe buffer it blocked in `write()` and stopped answering HTTP — a hang with no output, indistinguishable
  from an unresponsive provider. A bounded tail of that output is now attached to a provider-timeout error,
  which previously stringified to nothing at all — the tail is read under the same lock the drain threads
  hold, so collecting it cannot raise `deque mutated during iteration` in place of the failure it explains
  (#449)
- A provider timeout no longer kills the review. `ProviderTimeoutError` on the opencode path returned an
  `AgentResult` with no `retryable` metadata, and the model chain gates on that flag alone, so the single
  most recoverable failure there is read as permanent and terminated the run at attempt 1 of 10 — leaving
  the PR with no review rather than a review from the next model in the chain. Gateway 429/5xx responses on
  the same path were mis-classified the same way. Two bounds keep the retries from multiplying: opencode
  gets the initial attempt plus exactly one retry, and the chain now honours a wall-clock deadline derived
  from `RunBounds.run_timeout_s` instead of relying on the attempt cap alone. Every prompt on that path is
  covered, the initial review turn included — the likeliest one to time out, and the one whose timeout
  previously escaped the harness and aborted the chain outright. When the allowance runs out at the chain
  tail, the evidence packet now names the model that actually ran instead of the entry being skipped (#444)
- `mergecraft --version` reported `0.1.0` while the project was at `0.1.0a1`: the number was restated as a literal in `mergecraft/__init__.py` alongside `pyproject.toml` and the two drifted. It is now read from the installed distribution. The value also keys the offline result cache and is stamped on telemetry and eval reproducibility pins, so the mismatch quietly mixed artefacts from different builds
- Managed analyzers no longer report a clean scan as skipped: the adapter's fallback re-parse ran on the
  human-readable output string, which carries the `version_note` prose prefix, so any managed tool whose
  findings stream was empty failed with `Expecting value: line 1 column 1 (char 0)`. TruffleHog hit this on
  every secret-free scan, making a passing scan indistinguishable from a broken analyzer. The fallback is
  removed (it could only duplicate the file parse, and bypassed finding redaction when it did), the output
  read is classified separately so an undecodable file no longer raises `UnboundLocalError`, and analyzer
  output is persisted only from the raw stream
- `staticChecks` withholding no longer depends on how a gate was declared: with `shell: disabled` on an
  untrusted run, gates discovered from the repo's Makefile executed while configured ones were correctly
  withheld — meaning commands from a Makefile that is itself part of the diff under review could run.
  Both routes now go through the same cannot-run reporting, each with a truthful reason
- `review --dry-run` skips the analyzer catalog while still materializing the diff and returning the review prompt (#401)
- `load_audit_events` skips malformed JSONL lines and non-dict payloads instead of raising (#398)
- `route_model` routes security specialist at `critical` risk to the same capable model as `high` instead of Haiku (#394)
- Checkout and packaged `defaults.yaml` copies drifted after README v2; `make pins-check` gates byte identity (#402, #414)
- Hermes generated skill package lists `GEMINI_API_KEY` and `NOUS_API_KEY` (not `GOOGLE_API_KEY`) in `required_environment_variables`, matching `docs/authentication.md` (#415)
- Coverage ratchet floor raised to 80% after new docs contract tests increased measured line coverage above the prior ceiling
- Transitive `h2` 4.4.0→4.4.1 in `uv.lock` for `pip-audit` (PYSEC-2026-3628)
- `mergecraft init` no longer emits `uses: ./` in consumer repos — published Action ref instead (V8/D13)
- `mergecraft init` scaffold drops comment triggers and unsafe `github.event.comment.body` prompt wiring; defaults to `CLAUDE_CODE_OAUTH_TOKEN` (README Example 1 parity)
- Offline `mergecraft review` no longer runs the analyzer catalog twice: the pre-pass in
  `run_offline_analyze` and the reviewing agent's `run_analyzers` call each provisioned tools and
  executed every eligible analyzer over the same diff, doubling review time and duplicating the
  skip block, sandbox probe, and semgrep/trufflehog output in the log. The pre-pass now records the
  inputs it ran under (repo root, changed files, trust tier, shell, analyzer mode, inline budget,
  offline flag, base ref, and a digest of the diff) and `run_analyzers` reuses that result when every
  one of them matches; any difference — and the GitHub Action path, which has no pre-pass — runs the
  pipeline exactly as before
- Offline analyze stores ``AnalyzerRunState`` on the CLI tool context and merges analyzer findings into structured output so CC1 exit codes see Critical/Major hits the agent omitted; result-cache keys include mergeCraft version and a settings digest (#399)
- Managed analyzer binaries are re-verified on every cache hit, not just at download time: the cache
  directory is keyed by the *archive* sha256, so a tool that rewrites itself in place was executed on
  every subsequent run while the path implied the pinned contents. TruffleHog's built-in updater did
  exactly that, silently replacing the pinned 3.96.0 binary with 3.97.0. Provisioning now records the
  installed binary's sha256 beside it and refuses to reuse a cache entry that no longer matches —
  discarding it (updater state included) and re-provisioning from the pin, or failing closed with a
  truthful skip reason when the pinned source is unreachable. TruffleHog is additionally run with
  `--no-update` so the updater never fires

### Changed

- Offline `--use-cache` / `--resume` store only after structured-output finalize and re-validate on hit; cache keys include trust tier, `--prompt`, and related review inputs; `--resume` reads that cache and does not call a no-op checkpoint stub (#378)
- CLI, Action, and SCM share one four-stage review engine (materialize / analyze / review / publish) with per-stage timeouts recorded after each stage; the 1h review budget is snapshot data (the agent self-times); `--resume` is an alias of `--use-cache`; `--agent` negotiates `MERGECRAFT_AGENT_PROTOCOL` and stamps protocol budgets, emitting `phase` events as each engine stage starts (#378, #379, #380)
- Eval methodology: blocker precision is `None` (unpublished) when a run reports no blockers, and severity accuracy is `None` when there are no locality matches — never a vacuous 1.0
- Landing README redesigned as a REACH-style product page (outline B): problem/solution
  cards, D2 architecture hero, numbered install, and jump-nav. Long-form install,
  authentication, and workflow essays moved to `docs/install.md`,
  `docs/authentication.md`, and `docs/workflows.md`.

### Added

- `mergecraft review --shell {disabled,restricted,enabled}` — operator opt-in that makes the seven
  `runtime: repo-native` analyzers (ruff, mypy, bandit, vulture, typos, jscpd, markdownlint) reachable from
  the offline CLI. The offline path previously hardcoded `shell: disabled` at three sites, so those tools
  could never run locally under any configuration and a full local review exercised only the two managed
  analyzers. Defaults to `disabled`, so runs that omit the flag are unchanged; raising it lets analyzers
  execute tooling supplied by the repository under review and is unsafe for untrusted code
- Consumer glossary (`docs/glossary.md`) — plain-language definitions for trust tier, typed
  findings, blast radius, and related landing-page terms; manifest row and `llms.txt` entry.
- Per-harness Agent Skills packages generated from `skills/mergecraft/SKILL.md` via
  `scripts/gen_agent_packages.py`, with `skills/harnesses.yaml` install matrix,
  `make agent-packages-check` in CI, and Hermes/OpenClaw surfaces (#383 bullet 1, RV3)
- Runnable CLI example trees under `examples/cli/` (local diff, branch range, patch
  file, and `--agent` JSONL) with `make cli-examples` / `cli-examples-check` and
  `docs/cli-examples.md` tour page
- Agent-loop reference workflow (`docs/agent-loop.md`) for `mergecraft review --agent` (#383)
- CLI, GitHub Action, and SCM webhooks now enter one review engine over one immutable snapshot (#380)
- `mergecraft explain`, `ask`, and `replay` plus `run inspect` / `run diff` print output-only change, line Q&A, and stored-run views (#377)
- `mergecraft review --agent` negotiates protocol version against CLI JSON `schema_version` (both fields kept, aliased), reports retryable mismatches, and names token/cost/tool-call budgets (#379)
- `mergecraft review --agent` streams the first finding before the verdict; `--use-cache` and `--resume` reuse a local result cache; cancelling a review cleans up child processes (#378)
- Generated six-axis support matrix (`docs/support-matrix.md`), RC/soak release process (`docs/release-process.md`), and a security-response plus coordinated vulnerability-disclosure path in `SECURITY.md` (#382)
- Eval methodology (#384): quality metric set (`mergecraft.evals.quality_metrics`), ablation harness (`mergecraft.evals.ablation`), expanded human-reviewed golden corpus plus a separate synthetic mutation corpus (`mergecraft.evals.corpora`), and a `docs/eval-methodology.md` page registered in `docs/manifest.yaml`. Scores stay off the landing README; #140 still owns publishing precision/recall/F1.
- Enterprise runtime (`mergecraft.enterprise`): offline/self-hosted install plan citing the Python 3.11 floor, HTTP(S) proxy with `HTTPS_PROXY`/`NO_PROXY` export, custom CA certificate loading via `ssl.SSLContext`, data-residency allow-list enforcement, configurable telemetry with on/opt-out/off modes, support bundles with secret redaction, audit-log and usage/cost export, blocking-decision explainability, trace-retention policy with privacy-aware log mode, operational diagnostics, organisation policy/memory distribution without a dashboard. New CLI verbs: `mergecraft health`, `mergecraft audit export`, `mergecraft support-bundle`. (#381)
- Agent install surfaces: `AGENTS.md`, consumer skill (`skills/mergecraft/SKILL.md`),
  Claude plugin manifests (`.claude-plugin/`), slash commands (`commands/`),
  GitHub Copilot instructions (`.github/copilot-instructions.md`), curated
  `llms.txt`, and a **For AI coding agents** section on the landing README.
- `llms-full.txt` generated concatenation plus docs pin/link gate (`make llms-check`,
  folded into `make docs-check`).
- Added: generated CLI and Action reference pages (`docs/cli.md`,
  `docs/action-reference.md`) plus a docs manifest; `make docs-check`
  replaces landing-README table splices.
- Provider routing now tracks capability dimensions (context, reasoning, tools, structured IO, cost, latency, residency), require/prefer/fallback intents, per-specialist and per-risk model selection, heterogeneous verifier/judge models, health tracking, bounded retryable-only retries, circuit breakers with cooldown, degradation when a non-required provider is down, fail-closed required-model pins, run-manifest provider/model hashes, per-provider budgets, routing-quality eval, residency allow-lists, and a nightly catalog smoke (#371)
- Review specialists now report unique useful findings plus latency, cost, precision, and recall; specialists that add cost without review value can be skipped via per-agent circuit breakers (#370)
- Review profiles now include `standard`, `api_compatibility`, `migration`, `monorepo`, and `cross_repo` (hyphen aliases on the CLI); `mergecraft profile recommend --risk` auto-selects from change risk, with CLI then policy overrides; profile budget exhaustion stays `inconclusive`, never a clean pass (#369)
- `.mergecraft/config.yaml` now carries a `schema_version`; unversioned files migrate on load, unknown versions fail closed, and deprecated keys warn before a breaking removal (#368)
- Review profiles now carry an explicit latency budget; ensemble spend over the profile cost ceiling fails closed; cheap classification runs before specialists, independent work can run in parallel, and structural summaries compress context before an LLM step; early-stop fires when evidence is already sufficient, routing considers remaining budget, and regression/monorepo benches exist without publishing measured cost or latency numbers (#367)
- `mergecraft doctor --supply-chain` verifies lockfile reproducibility, bundled agent-CLI provenance, and analyzer version pins; every run manifest now records runtime and tool versions (#366)
- Failure-injection, soak, high-concurrency, monorepo, and large-PR harnesses now pin production SLOs for review completion, time to first finding, total review latency, and publication success, with a closed reliability error taxonomy and per-stage latency metrics (#364)
- A mid-review provider outage degrades instead of crashing; corrupt local cache rebuilds, disk and memory preflight fail closed, giant repositories skip or partial, SCM publication is idempotent, runs resume from a checkpoint, cleanup runs on timeout/cancel/crash, and diagnostic bundles redact secrets (#365)
- `mergecraft eval gate` now blocks a release when a prompt-injection, malicious-repository, or malicious-ticket corpus case regresses; reviewing a local path or public URL treats the tree as attacker-controlled input (#363)
- `mergecraft memory validate` checks the learnings store; learned behaviour needs historical evidence or explicit approval; factual / policy / preference / false-positive memory stay distinct; organization memory is a pluggable backend; effectiveness metrics prove precision rises without losing recall (#360)
- `mergecraft policy effective` and `simulate` resolve the effective rule set (with the source of every rule, including symbol scope), detect same-scope enforcement conflicts, emit policy audit artifacts, and report trigger / false-positive / waiver / blocking rates (#358)
- Shipped policy packs for security, public API, migrations, dependency changes, authentication/authorization, testing, and operational readiness; each rule keeps stable identity fields and ships should-trigger / should-not fixtures for `mergecraft policy test` (#359)
- `mergecraft context search` and `explain` score retrieved context, allocate per-specialist token budgets, fetch lazily through controlled tools, and record omitted scope so the evidence outcome is downgraded; retrieval quality is scored separately from the model (#356)
- Reviewed-repo instruction discovery now includes `GEMINI.md`, GitHub Copilot instructions, Windsurf rules, `SKILL.md`, and a configurable extra list; injected instruction bytes are hashed into the run manifest, competing sources record a winner, untrusted files stay inside the nonce fence, and `--context` files enforce type, size, trust, and provenance (#357)
- Review findings are ranked by materiality (security outranks style), confidence is calibrated from benchmark hit rates, and publication/blocking floors plus per-severity, category, file, and review budgets are configurable; dismissals record a closed reason code for evaluation (not durable memory), and a release-wired corpus gate requires blocker precision above 95% (#355)
- `mergecraft evidence show` and `verify` display and replay a finding's evidence packet (six verifier states, freshness, provenance hash, completeness); unverified findings do not block unless policy allows it, and a failed verifier cannot promote a finding to proven (#354)
- `mergecraft xrepo explain` reports SHA-pinned linked-repo producer/consumer contract breakage without writing the reviewed tree; policy can require cross-repo review before a public-contract change passes (#353)
- `mergecraft requirements inspect` and `explain` map ticket and local-spec text to requirement states without writing the reviewed tree; policy can require that evidence before a review passes (#352)
- `mergecraft describe` prints an output-only PR title, summary, walkthrough, risk, labels, TODOs, effort band, split advice, and similar-change notes (#351)
- `mergecraft capabilities` prints the review-only capability manifest (modes Review, IncrementalReview, Plan; identify / investigate / verify / explain / prioritize / suggest) (#350)
- Python 3.11 install floor (#343, option A): `requires-python` lowered to `>=3.11`; mypy/Pyright target 3.11; CI matrix runs on 3.11 and 3.14. README and `docs/distribution.md` install copy use stock `uv` from git (PyPI not published); Docker remains for pinned runtimes. Parenthesized the last PEP 758 site in `analyzers/detect.py` for the 3.11 compile gate; `harbor` extra gated to Python >=3.12.
- Python 3.11 floor ADR (#343, option A): `docs/dev/python-version-floor.md` records parenthesize-now / binary-later (D8). PEP 758 multi-type `except` handlers under `src/mergecraft/` are parenthesized (44 sites / 27 files).
- JS/TS lint: `biome` and `eslint` declare `supports_fix: true`; the JS-lint exclusive group (`js-lint`) now resolves the winner by config-file presence alone — `biome.json`/`biome.jsonc` beats any eslint config; eslint config beats any oxlint config — package-script and dependency signals are only consulted when no config file is found (D17, #310)
- `mypy` is now the default type checker for Python repos with no explicit type-checker config: auto-enabled when neither `pyrightconfig.json` nor `[tool.pyright]`/`[tool.basedpyright]` is present (D16, #309)
- `osv-scanner` detect globs now include `uv.lock`, so repos using uv's lock file trigger vulnerability scanning without pip-audit (#309)
- docs: `flake8` and `pylint` catalog entries note they are legacy opt-in; enabled via config override only (#309)
- Catalog manifests for `knip` (JS/TS unused exports/dependencies, `scope: repo`, `category: quality`) and `vulture` (Python dead code, `scope: repo`, `category: quality`) (#337)
- Catalog manifests for `govulncheck` (Go vulnerability scan, `scope: repo`, network allowlist `vuln.go.dev`), `cargo-audit` (Rust advisory vulnerability scan, `category: vuln`), `cargo-deny` (Rust license/advisory check, `category: license`), and `typos` (universal typo checker, `scope: repo`, `supports_fix: true`) (#337)
- Catalog manifests for `tsc` (TypeScript whole-program lint, `scope: repo`, `--noEmit`), `bandit` (Python security, version pinned to `make security` pin `1.9.4`), and `jscpd` (copy-paste detection, `scope: repo`, diff-line attribution via existing `filter_to_diff` pipeline — pre-existing clones off the diff are dropped) (#337)
- Flip `golangci-lint`, `clippy`, `rubocop`, `phpstan` to `default_enabled: auto`; adds `go.mod`, `Gemfile`, `composer.json` to their detect globs; RuboCop gates on config presence (D11 — silent without `.rubocop.yml`/`Gemfile gem`); PHPStan injects `--level=0` when no `phpstan.neon` is found (D12) (#338)
- `detekt` flipped to `default_enabled: auto`; activates on any `*.kt` or `*.kts` change, or when `detekt.yml` is detected — provides the default Kotlin lint path (#317)
- `swiftlint` flipped to `default_enabled: auto`; activates on any `*.swift` change or when `.swiftlint.yml` is detected — provides the default Swift lint path (#318); reports `unavailable` on Linux runners (requires macOS, `declared_unavailable`)
- `sqlfluff` flipped to `default_enabled: auto`; activates on any `*.sql` change or `.sqlfluff` config presence — skips silently when no SQL dialect is declared (#319)
- `stylelint` flipped to `default_enabled: auto`; activates on any `*.css`/`*.scss` change or `stylelint.config.js`/`.stylelintrc.json` presence — provides the default CSS lint path (#320)
- `htmlhint` flipped to `default_enabled: auto`; activates on any `*.html` change or `.htmlhintrc` presence — provides the default HTML lint path (#321)
- `yamllint` flipped to `default_enabled: auto`; activates on any `*.yaml` or `*.yml` change or `.yamllint` config presence — provides the default YAML lint path (#323); `shellcheck` and `hadolint` were already `auto` (#322, #324)
- `checkmake` flipped to `default_enabled: auto`; activates on any `Makefile`, `makefile`, or `*.mk` change — provides the default Make lint path (#325)
- `markdownlint` flipped to `default_enabled: auto`; activates on any `*.md` change or `.markdownlint.json`/`.markdownlint.yaml` presence — provides the default Markdown lint path (#326)
- `tflint` and `checkov` both flipped to `default_enabled: auto`; activate on any `*.tf` or `*.tfvars` change; the shared `iac-scanner` exclusive group was removed (split to `exclusive_group: null`) so both tools run concurrently — `tflint` provides Terraform lint, `checkov` provides IaC security scanning (#327)
- `luacheck` flipped to `default_enabled: auto`; activates on any `*.lua` change or `.luacheckrc` presence — provides the default Lua lint path (#328)
- `fortitude` flipped to `default_enabled: auto`; activates on Fortran files (`*.f90`, `*.f95`, `*.F90`, `*.f03`, `*.f`, `*.for`) or `.fortitude.toml` — provides the default Fortran lint path (#329)
- `regal` flipped to `default_enabled: auto`; activates on any `*.rego` change — provides the default Rego/OPA policy lint path (#330)
- `psscriptanalyzer` flipped to `default_enabled: auto`, adds `*.psd1` detect glob, and sets `supports_fix: true` — provides the default PowerShell lint and auto-fix path (#331)
- `blinter` flipped to `default_enabled: auto`; activates on `*.bat`/`*.cmd` changes — provides the default Windows Batch lint path (#332)
- `shopify-theme-check` flipped to `default_enabled: auto`; gates on `.theme-check.yml` or the canonical Shopify theme layout (`sections/`, `templates/`, `snippets/` dirs) — bare `*.liquid` files do not trigger it (#333)
- `smarty-lint` flipped to `default_enabled: auto`; `ANALYZERS.md` notes that `*.tpl` is ambiguous (Go templates, Terraform) — enable only when `.smarty-lint.json` confirms Smarty intent (#334)
- `ember-template-lint` flipped to `default_enabled: auto`, sets `supports_fix: true`; gates on `ember-cli-build.js` or `ember-source` in `package.json` — bare `*.hbs` files do not trigger it (#335)
- `prisma-lint` flipped to `default_enabled: auto`; ships a conservative fallback ruleset (`prisma-lint-default-rules.yml`) and sets `config_note` referencing it when no repo-level prisma-lint config is found — avoids inert no-op runs (#336)
- `cppcheck` flipped to `default_enabled: auto`; activates on any `*.c`, `*.cpp`, `*.h`, or `*.hpp` change — provides the default C/C++ SAST path (#315); `clang-tidy` remains `default_enabled: false` (requires `compile_commands.json`, C4)
- `pmd` flipped to `default_enabled: auto`; activates on any `*.java` change or `pmd.ruleset.xml` presence — provides the default Java lint path (#312); `infer` remains `default_enabled: false` (requires compilation database, C4)
- `phpcs` and `phpmd` remain `default_enabled: false`; catalog entries note they are legacy opt-in — `phpstan` (auto) is the default PHP signal (#316)
- `brakeman` flipped to `default_enabled: auto` with tight Rails detection — only activates on Rails marker files (`config/application.rb`, `config/routes.rb`), never on plain Ruby repos (#313)
- New catalog manifest for `bundler-audit` (Ruby gem vulnerability audit, `category: vuln`, `scope: repo`, detects on `Gemfile.lock`) (#313)
- `scripts/check_type_ignores.py` fails when a `type: ignore` or `cast(` in allowed `src/mergecraft/` lacks a one-line reason (#275); wired into `make lint`
- `scripts/check_xpass.py` fails when unexpected pytest xpasses remain on the allowed test tree (#276)
- xpass ratchet now runs as a `pytest_sessionfinish` conftest hook inside the coverage-gate pytest session — no standalone log file or extra CI step (#276)
- `MERGECRAFT_LIVE=1` opt-in gate for live provider tests (#278): `tests/conftest.py` centralizes skip policy via `pytest_collection_modifyitems`; `make test-integration-live` and the CI `integration-live` job export the flag so the suite stays fail-closed when secrets are absent
- `UnsupportedScmCapability` raised by `GitLabScmAdapter` now reports `"GitLab support is not available in this release"` instead of only the raw capability token; GitLab message is passed explicitly via `message=` so the generic format string stays clean (#279)
- docs: README requirements and `docs/distribution.md` Marketplace copy state that mergeCraft 0.1.0 is GitHub-only; GitLab support is planned via the `ScmProvider` abstraction (#279)
- docs: README SHA-pin advice now links to CONTRIBUTING.md verify one-liners (`cosign verify` / `gh attestation verify`); `docs/distribution.md` Marketplace gate requires image attestations to pass before listing, pointing at the existing `sign-attest` job (#280)
- SCM abstraction: `ScmProvider` protocol with `GitHubScmAdapter` (behaviour-preserving) and demand-gated `GitLabScmAdapter` that declares unsupported capabilities instead of emulating GitHub; core MCP tools and review publication route through `ToolContext.scm`
- Added: a test-only provider-harness fixture schema and strict matcher
  (`tests/support/provider_harness`) so deterministic review tests can name
  the exact provider interaction they expect. Not used in production.
- Added: provider-harness recording workflow and operator docs
  (`docs/dev/provider-harness.md`); opt-in sanitized capture under
  `.ignorelocal/provider-harness/records/`.
- Cross-repository intelligence indexes linked repos at pinned commits, contract surfaces (OpenAPI, GraphQL, protobuf, exports), cross-repo blast radius, reproducible citations, and ticket acceptance-criteria mapping under `mergecraft.xrepo` and `mergecraft.requirements`
- Repository context engine indexes repo maps, per-file symbol indexes (tree-sitter with generic fallback), provenance citations, and trust-gated instruction/skill discovery under `mergecraft.context`
- Call graph, change graph (changed symbol → dependents → tests → contracts), budget-aware dynamic expansion, targeted git blame, and `mergecraft context inspect` for provenance-backed context retrieval
- Feedback capture for findings (accepted / dismissed / disputed) keyed by fingerprint, with bounded negative-memory suppression, TTL/recency weighting, contradiction detection, and `mergecraft memory list|show|forget|export|import|feedback` lifecycle verbs (DG7)
- Policy-as-code package (`mergecraft.policy`) with schema-validated YAML rules, deterministic org/repo/path scoping, enforcement modes mapped onto the existing approval gate (D7), required-evidence inconclusive handling (D8), and bounded exceptions with expiry
- `mergecraft policy lint|test|explain` — validate policy rules, run should-trigger/should-not fixtures, and list effective rules with source layers
- Per-run budgets, bounded external-operation timeouts, and honest large-diff degradation (`RunBounds`, scope reduction reports, downgraded outcomes) for offline and Action reviews
- Large-PR review engine (DG2): cluster changed paths by dependency and intent, build hierarchical diff context (map → summaries → raw hunks) with token-budget scope reduction that reserves verbatim hunks for high-risk regions, record disputed/waived/stale finding lifecycle states, and emit advisory-only PR split recommendations from independent change groups
- Finding precision pipeline (DG1): deduplicate agent/analyzer findings before publication, apply a code-defined severity rubric at the verifier seam, require structured causality on blocking findings, suppress pre-existing analyzer hits via baseline comparison, and classify generated/minified/vendored paths for review policy
- DG1 precision corpus gate (`evaluate_dg1_precision_corpus`) proving recall holds while corpus-confirmed precision improves over the pre-DG1 baseline
- PR utilities (DG8): standalone describe output (`mergecraft.pr.describe`), text-only changelog/docs/test suggestions (D11), deterministic TODO scan, classifier-derived effort bands, advisory label suggestions, and `/mergecraft review` comment routing with author-association and permission gating (`mergecraft.mcp.comment_router`)
- `mergecraft mcp serve` and `mergecraft mcp list` expose the reviewer's MCP tool surface to external clients without widening trust tier or tool-class policy (D13)
- Named review profiles (`--profile fast|deep|security`) bundle model chain, analyzer focus, and run budgets; explicit CLI flags still win
- `mergecraft cache info|clear|prune` inspect and maintain the byte-bounded on-disk run cache
- `mergecraft doctor` diagnoses git, provider credentials, analyzer detection, auth, config, and MCP port availability without printing secrets
- `mergecraft config show|explain|validate` generalizes precedence inspection beyond tracing; local private-repo reviews ship no remote telemetry by default (D11)
- `mergecraft plan` previews model chain, toolset, analyzer detection, and token estimate without provider calls
- Run manifest fingerprints (model/CLI versions plus prompt, config, and policy hashes) for reproducible offline reviews
- `mergecraft review` machine contract: distinct process exit codes per `RunOutcome`, `--format text|json|jsonl|sarif`, and `--agent` JSONL streaming with an explicit `protocol_version`
- Added review-wide trace correlation: a `review.id` on every span across every process and agent of one logical review, plus a deterministic `review.correlation_key` (`sha256(repo|pr|head_sha)`) that groups re-reviews of the same commit; `trace_id` remains per agent run
- Added tracer baseline attributes (`mergecraft.run_id`, `mergecraft.version`, `mergecraft.trust_tier`, VCS and CI fields) merged into spans at close time, with explicit attributes taking precedence
- Added review-context env propagation into spawned agent CLI subprocesses, so subagent runs join the parent review's trace identity
- Added a content-capture policy for model payloads (`tracing.content`: `off` / `metadata` / `redacted` / `full`, default `redacted`; env `MERGECRAFT_TRACING_CONTENT`) gating whether LLM bodies may be emitted onto spans, with per-payload size counts and a sha256 of the original at every level above `off`
- Security: spans from untrusted sources are hard-capped at `metadata` content capture — prompt/completion bodies can never be shipped to a sink for an untrusted review, and the cap cannot be overridden by config or env
- Added model-parameter and payload capture on LLM spans (`gen_ai.request.*` / `gen_ai.response.*` / `gen_ai.usage.*`), recording both the requested and executed model so fallbacks are visible, with extended-thinking capture gated by the content policy and per-harness coverage documented (CLI harnesses have no payload visibility; the OpenCode HTTP path and stream consumer do)
- Added richer tool-call tracing: `gen_ai.tool.call.id` correlating request and response, per-call duration, and an MCP-vs-native origin distinction
- Added outcome spans: review-phase spans, per-agent run spans with MCP-stamped attribution (`MERGECRAFT_AGENT_ID`) so tool calls chain under their agent, fingerprint-keyed finding lifecycle spans, a verdict span with a derived disagreement flag, and eval-score spans that inherit the active `review.id`
- Added benchmark quality metrics: blocker precision scored separately from overall precision, semantic duplicate rate, unique accepted findings per lens, judge value (noise removed and recall lost), p50/p95 cost-latency summaries, and orchestrator kind as a scored dimension
- Added an adversarial eval corpus (`evals/cases/adversarial/`) proving the prompt-injection fence holds against hostile PR bodies, review comments, and commit messages, and that poisoned context can neither suppress real findings nor manufacture approvals
- Added `mergecraft eval gate` — a release regression gate comparing a candidate result set against baseline with a declared tolerance band, wired as a blocking job in the release workflow
- Added agent registry binding model, prompt, toolset and budget per role with `mergecraft agents list|show|set` and `make agents-check`
- Added registry-driven harness render for Claude, OpenCode, Codex, Gemini, and Cursor with per-agent models and declared Codex degradation in run metadata
- Added typed specialist handoff, model-diversity policy for verification, and ensemble or shadow dispatch modes on agent bindings
- Added change classifier and risk-based lens routing with recorded per-lens reasons in Review mode
- Promoted 20 themed review lenses from Review prose into registry entries with `mergecraft lens list|show|test`
- Added pluggable orchestrator with declarative pipeline file, trust gate for untrusted sources, and `mergecraft pipeline lint|show|explain`
- Added declared decision nodes for hybrid orchestration — typed triviality, lens selection, and finding disposition seams with pipeline-owned control flow
- Added: optional `harness` setting (`opencode` / `codex` / `claude` / `gemini` / `cursor`) to select the agent runtime independently of provider/model. Existing configs with the key unset keep today's inference
- Added: terminal-verdict protocol shadow mode (`gates.terminal_verdict`, default `shadow`) with a closed `VerdictDiagnostic` vocabulary; enforce still applies the fail-closed missing-verdict branch
- Added: server-side semantic validation of the terminal verdict — `request_changes` with no findings, `approve` over a verifier-confirmed blocker, and `approve` with a failing required deterministic check are all rejected and fail closed
- Added: `submit_review_verdict` — a typed MCP operation that records a review's terminal verdict
  (`approve` / `request_changes`), summary and structured findings. Unknown fields and invalid
  verdict values are rejected; an identical re-submission is idempotent, a conflicting one is an
  error. Not yet enforced — the run outcome is unchanged in this release
- `mergecraft tracing logfire wire-workflow` / `unwire-workflow` — surgical
  YAML mutation of `.github/workflows/*.yml` to wire (or strip) the four
  Logfire keys (`tracing: "true"`, `tracing-to: logfire`,
  `logfire-token: ${{ secrets.LOGFIRE_TOKEN }}`,
  `MERGECRAFT_TRACING_PROJECT: ${{ vars.LOGFIRE_PROJECT }}`) on selected
  steps. Comment-preserving line-based mutator; refuses forks with
  similarly-named action names; supports both the multi-line
  (`- name: ...` / `  uses: alexhawat/mergeCraft@X`) and the inline
  (`- uses: alexhawat/mergeCraft@X`) step forms; creates a `with:` block
  when absent (README Example 1 has no `with:`); public API under
  `mergecraft.cli.tracing_logfire_wf_yaml.apply_logfire_wiring` /
  `remove_logfire_wiring` / `render_workflow_diff`
- `scripts/gen_reference_docs.py` regenerates README's `action.yml` input/output
  tables and CLI command table from the live sources (never a subprocess — it
  walks the live Typer `app` object) and splices them between HTML sentinel
  comments; `make reference-docs-check` (wired into `make ci-static`) fails the
  build on drift. Closes the audit in the issues-showcase-readiness wave plan
  (PR G2): the README table documented 9 of 24 real `action.yml` inputs and
  neither declared output anywhere

### Changed

- `mergecraft review` uses `--output-format {text,json,jsonl,sarif}` (not `--format`) so it no longer collides with root `--format {table,json}`; root `--format json` selects JSON when `--output-format` is omitted; explicit `--output-format text` wins over inherited JSON. Human-readable review text stays on stderr (D14) — document `2>` for capture.
- Thermo-nuclear CLI remediation: global `--format json` now drives every `--json`-capable subcommand (`eval`, `findings`, `learnings`, `memory`, …) with a pinned `schema_version`; invalid `--log-level` exits `2`; eval replay regressions exit `12` (`CLI_FAILED_EXIT_CODE`); duplicate `_bail()` helpers collapsed to `mergecraft.cli.errors.cli_bail`; `CLI_SUCCESS_EXIT_CODE` / `CLI_USAGE_EXIT_CODE` moved to `mergecraft.cli.exits`; colour policy runs once via pre-help bootstrap. `findings export` uses `--output-format {json,markdown}` (not `--format`) so it no longer collides with the root `--format {table,json}` switch; explicit markdown wins over inherited JSON. `eval_cmd` split into `eval_cli_output.py` / `eval_gate_cmd.py`; `diff_review_cmd` and `gha_cmd` route exit helpers through `mergecraft.cli.exits`.
- Global CLI surface (#342): root `--format {table,json}`, `--quiet` / `--verbose` / `--log-level`, and `--color {auto,always,never}` honour `NO_COLOR`, `FORCE_COLOR`, and non-TTY sinks; JSON payloads carry `schema_version`; `review` is the documented command and `diff-review` is a hidden deprecated alias (one stderr line per invocation).
- CLI exit-code contract (#341): every exit under `src/mergecraft/cli/` routes through named constants (`mergecraft.cli.exits` / `RunOutcome` helpers); usage errors exit `2`. See [`docs/EXIT-CODES.md`](docs/EXIT-CODES.md). **Breaking:** scripts that branched on exit code `1` for generic CLI failures must follow the new table (most former `1` paths now exit `30`).
- Shell completion for the `mergecraft` CLI: `mergecraft --install-completion` (bash/zsh/fish) and `mergecraft --show-completion` (#340). CLI status and Rich chrome now go through shared stderr consoles; machine-readable `--json` payloads stay on stdout only.
- Dependabot now batches patch and minor bumps into one grouped PR per ecosystem (pip, github-actions, docker, and the `docker/agent-clis` npm lockfile), with security updates in their own group and majors still opened individually; `open-pull-requests-limit: 5` caps each ecosystem
- `mergecraft review` skips PRs authored by `dependabot[bot]`: the gate failed closed on every version bump (the reviewer posted no `mergecraft-approval` check-run, so the enforce step's fail-closed branch blocked the PR). Both jobs are conditionally skipped rather than untriggered, so a rule requiring `mergecraft review` still reports. `changelog-preview` is deliberately left running — it already passes on bot PRs, and skipping a reusable-workflow caller would report under the bare caller job id rather than the two-part `changelog-preview / preview` check name. CI, CodeQL, the security-audit Verify job, and SHA pinning still gate these PRs
- `.github/agents/dependency-pr-manager.md` — dry-run-first sweep agent for the dependency-PR queue: classifies each bot PR into auto / review / blocked / suspicious lanes, diff-audits that a bump touches only its manifest and lockfile, and writes a per-major review brief instead of merging majors blind
- `mergecraft review --help` now states that no flags are required and includes full example commands for local worktrees, GitHub branches, and present or past PRs
- Stale pytest `xfail(strict=False)` markers that were already passing are now real tests; remaining allowed-tree xfails are strict (#276)
- Changed: `gates.terminal_verdict` now defaults to `enforce`; missing terminal verdict reports `inconclusive`. Operators can still set `shadow`
- Changed: `create_pull_request_review` now records through the same validator as `submit_review_verdict`; GitHub posting is an internal publisher, not an agent tool

### Fixed

- Evidence image uploads, issue comments, and PR label tools work on review-only runs again
- Linked-repo contract breakage is included in ordinary PR checkout, not only `mergecraft xrepo explain`
- Linked-repo checkout reads only operator-granted siblings, and skips a sibling whose HEAD is not the pinned SHA
- Incoming GitHub and GitLab webhooks fail closed without a configured secret; reused delivery IDs are rejected for the lifetime of the process
- Untrusted download and clone URLs are SSRF-checked, and binary downloads pin DNS to the validated addresses
- `bandit` now uses built-in `--format json` instead of the optional SARIF extra, so auto-enabled Python security coverage still runs on plain Bandit
- `bundler-audit` now runs the gem CLI (`bundler-audit check --format json`) instead of `bundle audit`, so Ruby lockfile audits actually execute
- `tflint` no longer passes changed `.tf` files as positional args (invalid since TFLint 0.47); it lints the working directory and the pipeline still scopes findings to the diff
- `phpstan`, `golangci-lint`, and `sqlfluff` now skip when a PR only changes enablement markers (`composer.json`, `go.mod`, `.sqlfluff`) and has no source files to lint, instead of running with empty paths or linting the whole tree
- `bundler-audit`, `cargo-audit`, and `cargo-deny` findings no longer fake a line-1 GitHub anchor when the tool did not report a line; crate/gem coordinates stay in the message
- `clippy` now runs as `cargo clippy --message-format=json` (package/workspace) instead of passing PR paths as cargo args, so auto-enabled Clippy keeps rustc JSON findings
- Auto-enabled analyzers whose stdout is not SARIF now keep findings: `cargo-audit` (`--json`), `cargo-deny` (`--format json`), `vulture` (line text), `tsc` (`--pretty false`), `knip` (`--reporter json`), `jscpd` (`--reporters json`), `bundler-audit` (`--format json`), `sqlfluff` (`--format json`), and `clippy` (`--message-format=json`); `typos` 1.32.0 already emits SARIF and stays on `parser: sarif` (Thermos Finding 1)
- A successful analyzer with empty stdout (for example a clean `tsc --noEmit`) is treated as passed instead of unavailable
- `tsc` project-level diagnostics without a file location (for example `error TS18003`) now surface as body-only findings instead of a silent pass
- `tsc` help text and other unmatched nonempty stdout now fail closed instead of counting as a clean pass
- Project-level `tsc` findings survive diff scoping when the PR only changes `.ts` / `.tsx` files
- `phpstan`: command changed from `--error-format=json` to `--error-format=sarif` so the output aligns with `parser: sarif`; previously the JSON output caused `parse_sarif()` to raise `ValueError` and silently drop all findings (Thermos Finding 1, #338)
- `brakeman`: command changed from `-o brakeman.sarif` (writes to file) to `-o -` (stdout) so the SARIF output is captured by the adapter; `parser: sarif` is unchanged (Thermos Finding 1, #338)
- MCP HTTP server now issues a separate bearer token for the orchestrator ``/mcp`` route; reviewer/verifier harnesses keep ``ToolContext.mcp_auth_token`` for their role endpoints (#349)
- OpenCode gateway ``extra_options`` generation knobs (temperature, ``top_p``, ``max_tokens`` when a context window is known) are applied through provider model ``limit`` / ``options`` and the primary ``build`` agent config instead of being copied into ``provider.options``; ``llm.call`` tracing stamps only params the config path actually applies (#295, #349)
- `tracing/genai`: `_optional_float` now rejects non-finite float values (`NaN`, `Inf`) and their string representations (`"nan"`, `"inf"`), matching the existing behaviour of `_optional_int`; invalid temperature/top_p degrade to omitted knobs instead of propagating the sentinel value (#348)
- OpenCode ``llm.call`` spans now carry ``ModelParams`` request knobs (``gen_ai.request.max_tokens``, temperature, and siblings) resolved from gateway ``extra_options`` env vars (``MERGECRAFT_CUSTOM_PROVIDER_EXTRA_OPTIONS``, indexed ``…_<N>``, or per-provider ``MERGECRAFT_PROVIDER_EXTRA_OPTIONS``) including named presets when only ``NOUS_API_KEY`` / ``TOKENHUB_API_KEY`` are set (#295)
- OpenCode HTTP ``llm.call`` usage attrs omit unset counters instead of zero-filling ``gen_ai.usage.*`` when the session response reports output tokens only (#297)
- `mcp/server`: `submit_review_verdict` (`TERMINAL_PROTOCOL`), `verify_agent_findings` (`VERIFICATION`), and `record_finding_verdict` (`REVIEW_WRITE` + `mutates=True`) were absent from the primary `/mcp/reviewer` surface — the playbook's C6 "verify then publish" loop could not execute. `TERMINAL_PROTOCOL` and `VERIFICATION` are added to `PRIMARY_REVIEWER_ALLOWED_TOOL_CLASSES`; `record_finding_verdict` is added to `PRIMARY_MUTATING_ALLOWLIST`. Subagents keep `REVIEWER_ALLOWED_TOOL_CLASSES` (none of the three classes) and `READONLY_MUTATING_ALLOWLIST`, so they remain denied all three tools. Verifier still has no `record_finding_verdict` and no `terminal-protocol` tools
- `agents/claude`: `write_mcp_config` wrote a single MCP server entry pointing to `/mcp/reviewer` (derived from the orchestrator's `current_agent_id()` at `_run` start). Verifier subagents inherited that config and called `/mcp/reviewer` instead of `/mcp/verifier`. `write_mcp_config` now always writes two entries — `MERGECRAFT_MCP_NAME` → `/mcp/reviewer` and `MERGECRAFT_VERIFIER_MCP_NAME` → `/mcp/verifier` — without using `current_agent_id()`, so the verifier surface is available to subagents from the moment the orchestrator launches; `test_role_dispatch_urls.py` now tests the production call path rather than a fake `agent_run_span`
- `tracing/sinks`: `sink_factory` dedupes resolved `OTLPSink` instances by endpoint and headers before fan-out, so a `logfire` + `otel` pair aimed at the same OTLP destination emits one span per `TraceEvent` instead of N identical rows; the #293 processor singleton guard is unchanged (#372)
- `tracing/exporters`: `OTLPSink.write` now passes `TraceEvent.ts_start_ns` / `ts_end_ns` into OTel `start_span` / `span.end`, so Logfire span duration matches provider wall time instead of zero-width export-time stamps; the `duration_ms` attribute is unchanged (#373)
- `tracing/exporters` / `tracing/otel_bridge`: exported spans now carry OTel parent context from `parent_span_id` and use mergeCraft `span_id` (first 16 hex chars) as the OTel `span_id`, so Logfire trace trees link correctly; `attach_trace_context` propagates the same ids for nested auto-instrumented calls (#374)
- `llm.call` spans now stamp `gen_ai.system`, `gen_ai.usage.*`, and `gen_ai.response.model` when the provider reports them, and `mergecraft.usage.unavailable=True` when it does not — driver parity across OpenCode HTTP, Claude streaming, and the model-chain close site; codex and gemini already stamped `gen_ai.system` on their streaming close paths (#375)
- `tracing/exporters`: `_setup_tracer_provider` no longer stacks a duplicate `BatchSpanProcessor` / OTLP exporter on every `OTLPSink` construction — when a real `TracerProvider` already exists and the same endpoint is already registered, the function reuses the existing processor pair instead of appending another one, eliminating the ~29× duplicate OTLP rows per span observed in production (#293)
- `tracing/tracer`: `get_tracer_from_settings` pins `MERGECRAFT_TRACE_ID` on first mint and reuses a process-wide `Tracer` when tracing settings match, so MCP-style `tools/call` handlers on a worker thread share one Logfire `trace_id` instead of minting a new tree per call (#292)
- `tracing/resolve`: ``MERGECRAFT_OTEL_ENDPOINT`` (or ``--otel-endpoint``) with no explicit ``tracing_to`` now selects an OTLP sink instead of falling through to ``jsonl_file`` — the endpoint env var implies OTLP export
- `tracing/_tool_attrs`: `enrich_tool_response` now classifies `ToolResult.is_error=True` as an error span even when no Python exception is raised — `tool.exit_code=error`, span status `error`, and `gen_ai.tool.output` set for the GenAI dashboard; JSON-RPC is unchanged (#296)
- `analyzers/trust`: `build_review_source` detects a linked git worktree of the same repo (same `git rev-parse --git-common-dir`) and sets kind `"local_worktree"`, which `derive_source_trust_tier` maps to `"trusted"` without `--trust`; temporary clones and unrelated repos remain `"untrusted"` (#294)
- `mcp/git_guards`: six guard functions (`_is_config_flag`, `_subcommand_declares_shorts`, `_reject_config_flags`, `_reject_namespace_flag`, `_reject_branch_writes`, `_reject_file_writing_flags`) and ten guard constants extracted from the 754-line `mcp/git.py` into a dedicated `mcp/git_guards.py` module; `mcp/git.py` re-exports every name so existing `monkeypatch` targets continue to resolve (#299)
- `cli/auth`: authenticating a provider left the contributor unable to run the CLI locally — `mergecraft auth codex|claude|gemini|cursor|nous|tokenhub|minimax` persisted the captured credential only through `gh secret set`, so it landed in GitHub Actions secrets and nowhere the local runtime reads. All seven now take `--scope local|github|both` (default `github`, so a CI-only setup keeps today's behaviour exactly, including the hard failure when the secret write fails), and `--scope local` needs no `gh` auth and no network. `auth codex` captures `auth.json` before its isolated `CODEX_HOME` tempdir is deleted, and the pretty-printed multi-line payload `codex login` writes is compacted to one line and quoted, so the `.env` entry round-trips through both `dotenv` and `source .env` (#221)
- `cli/auth`: running `mergecraft auth … --scope local` from a subdirectory reported success while writing a nested `.env` that nothing reads — the local path fell back to `.env` in the current working directory; it is now anchored at the git repository root, and a run with no repository to anchor to fails with a pointer to `MERGECRAFT_ENV` instead of writing somewhere useless. `$MERGECRAFT_ENV` still wins when set (#221)
- `agents/codex`: every Codex review failed to start whenever a custom OpenAI-compatible provider was configured (`MERGECRAFT_CUSTOM_PROVIDER_*`) — the generated `config.toml` emitted the `default_permissions` profile name *after* the `[model_providers.*]` tables, so TOML scoped it into a provider block and Codex never saw the read-only review permission profile; the generated file now always emits every root scalar ahead of the first table header, whatever order the writer populated them in, so the same ordering also covers `sandbox_mode` on the non-profile path (#222)
- `agents/structured_handoff`: a specialist handoff whose `---typed-findings---` marker differed in casing from the documented lowercase spelling lost every finding it reported — the marker was detected case-insensitively but the text was then split on the exact-case literal, so the payload came back empty and `parse_specialist_handoff` raised `ValueError: … not valid JSON` instead of returning the findings; the split is now a case-insensitive regex search over the original text, which keeps the offsets valid even when the prose half contains non-ASCII characters that `casefold()` would lengthen (#261)
- `agents/ensemble`: when two ensemble models disagreed, `reconcile_ensemble` returned only the primary model's findings, so a real problem that only the secondary reviewer caught — up to and including a Critical the primary missed entirely — was silently discarded and survived nowhere but the judge brief; the disagreement path now merges both models' findings, deduplicated by `_finding_key`, keeping the primary's copy of a corroborated finding and the judge escalation unchanged (#262)
- `agents/ensemble`: the same defect reported at two different call sites in one file collapsed into a single finding when the two ensemble models' results were merged, so the second site never reached the reviewer — the deduplication key was the path and the finding body only; the line is now part of a finding's identity, and a row with no line keys on a value no line number can collide with (#262)
- `agents/_stream_consumer`: streaming runs on OpenAI-shaped providers (Nous, MiniMax, opencode Responses / Chat Completions, Codex) over-reported their prompt size — and therefore the run's token and cost accounting — by the whole cached-prompt count whenever prompt caching was active, because `prompt_tokens_details.cached_tokens` / `input_tokens_details.cached_tokens` are already *inside* the reported `input_tokens` but were added to it a second time; `to_usage()` now adds the cached count only when it came from Anthropic's disjoint `cache_read_input_tokens` counter, and still reports it as `cache_read_tokens` in both cases (#273)
- `agents/opencode`: reviews served over the opencode HTTP session path — every Nous and MiniMax run — over-reported their prompt size, and therefore the run's token and cost/budget accounting, by the whole cached-prompt count whenever prompt caching was active; this path re-implemented the cached-token scan inline and kept adding OpenAI-style `prompt_tokens_details.cached_tokens` / `input_tokens_details.cached_tokens` to an `input_tokens` that already contained them, so the fix landed in `_stream_consumer` only covered the streaming CLI drivers. It now shares `_resolve_cache_read`, adding the cached count only when it came from Anthropic's disjoint `cache_read_input_tokens` counter, and still reports it as `cache_read_tokens` in both cases (#273)
- `mcp/verdict`: a pull request carrying an analyzer-reported Critical or Major could be approved as long as the reviewing agent never dispatched a verifier for it — `validate_submission`'s approve branch only walked verifier-confirmed findings, so skipping verification was a route to approval. Approve is now rejected whenever any finding the run knows about is still of blocking severity after the causality policy has run, whether or not a verifier looked at it, and a finding the gate cannot grade blocks rather than being skipped. The reviewing agent reopens the approve path by verifying and then `drop`ping a refuted finding, or by `downgrade` to a non-blocking severity — both are applied before the gate reads the state, and a `drop` recorded in an earlier run counts too. Attribution is deliberately not a second condition: under the default `baseComparison: diff` no base run happens and every diff-scoped finding stays `introduced_by_pr: "unknown"`, so gating on `"true"` exempted ruff, mypy, bandit and semgrep from the gate entirely; where a base run did happen, a pre-existing finding is stamped `"false"` and the causality policy already downgrades it below the blocking threshold (#263)
- `mcp/verification`: a verifier `downgrade` that named no `new_severity` silently rewrote the finding to `Minor`, so a single such verdict retired any Critical the approve gate was holding; a downgrade is now rejected unless it names the severity it downgrades to, that severity must be one of the four in the taxonomy, and a downgrade landing on a still-blocking severity needs the same structured causality a `confirm` does (#263)
- `mcp/check_runs`: the `list_check_runs` tool called GitHub's check-*suites* endpoint and returned a `check_suites` payload, so a reviewing agent that asked which checks ran on a ref got only per-suite rollups — the individual run names, their per-run conclusions, and therefore the logs of the one job that actually failed were unreachable through this tool; it now calls `list_check_runs_for_ref` and returns `check_runs`, and every returned run carries its parent suite's id as a top-level `check_suite_id` beside its own `id`, so the documented `get_check_suite_logs` follow-up can be handed a suite id without the agent having to pick between two nested ids. `GitHubScmAdapter.list_check_runs`, the protocol's MCP-read operation of the same name, forwarded to the suites endpoint too and is corrected with it (#266)
- `mcp/server`: a malformed `tools/call` from the reviewing agent — a missing required argument, an unreadable one, or a property the tool never declared — reached the tool body and failed in whatever ad-hoc way that tool happened to fail, or partially succeeded, instead of being rejected at the protocol boundary; `handle_rpc` now validates `arguments` against the tool's `input_schema` before dispatch and returns JSON-RPC `-32602` with the offending JSON path and the validator's message. A string-encoded scalar sent where the schema declares `integer`, `number` or `boolean` — `"1"`, `"true"` — is read as that type and passed through rather than rejected: roughly 37 tool bodies were written for exactly that tolerance and the packaged workflow itself asks the agent for a bare `check_suite_id`, so rejecting it turned a tolerated shape into a hard error and silently degraded CI-log grounding. A union that already admits `string` is left alone, and a value that cannot be read as its declared type is still reported as the schema violation it is. `inf` / `nan` spellings such as `"1e999"` are refused rather than coerced — they satisfy the schema and then raise inside the tool body — and only `true`/`false`/`1`/`0` read as booleans, since no JSON consumer recognises `yes`/`no`. A tool whose declared schema cannot be compiled fails closed as `-32603` naming that tool, rather than running unvalidated arguments — reachable in production because `set_output` adopts a consumer-supplied `output_schema` verbatim and only its JSON-object-ness was ever checked. A non-dict `arguments` is still coerced to `{}` and is now rejected by any tool that requires a property, where it previously executed with no arguments. A call rejected here is charged no tool-call budget, so a schema mismatch the agent retries cannot burn the run budget with nothing executed, and the rejection is recorded on the trajectory instead of being invisible (#267)
- `mcp/server`: a `tools/call` carrying a very long integer literal where the schema declares `number` — anything past the float range, from 309 digits up — returned HTTP 500 with no JSON-RPC envelope and no request `id`, which is the response shape Codex's MCP client cannot deserialize and answers by killing its transport worker. The non-finite guard added for the `inf`/`nan` spellings asked `math.isfinite()` about a Python `int`, which converts to float first and raises `OverflowError`, and argument coercion runs before the handler's error boundary, so nothing caught it. Only a float can be non-finite, so the guard now says so; a wide integer is passed through typed as any other number is. Reachable on every top-level `number` property, including `shell.timeout`, `git_fetch.depth` and the `check_suite_id` the packaged workflow asks the agent to pass to `get_check_suite_logs` as a bare number (#267)
- `mcp/verdict`: a malformed finding the reviewing agent asserted could silently neutralise a real analyzer blocker that shared its fingerprint — the grader marked the fingerprint as already graded before discovering the row was unreadable, so the analyzer row carrying it was skipped and landed in neither the unverified nor the ungradable population, leaving the approve gate with nothing to block on. A row that cannot be read no longer spends its fingerprint (#263)
- `mcp/shell`: the shell tool's git refusal missed `sudo -u <user> git …` and `doas -g <group> git …` — the target name is neither path-shaped nor numeric, so it read as the command word and ended the scan before the git behind it was inspected, putting the whole git surface (`git clean`, `filter-branch`, `-c alias.…`) back within reach of a `restricted` shell. A wrapper flag's separate name operand is now skipped rather than treated as the command (#257)
- `wait-for-ci` job now declares a job-level `permissions: {contents: read, checks: read}` block so its `gh api …/check-runs` poll is no longer silently 403'd; stderr from the poll is no longer suppressed so permission failures are visible in the job log (#264)
- `action.yml` outputs (`result`, `evidence_packet`, `verdict_diagnostic`) no longer carry `value: steps.run.outputs.*` composite-action wiring — those expressions are inert on a Docker action and prevented consumers from ever reading the outputs; outputs are now written exclusively via `$GITHUB_OUTPUT` (#272)
- `verdict_diagnostic` output is now written to `$GITHUB_OUTPUT` on every run — the declared output was computed but never emitted, leaving the key permanently absent for consumers; an empty string is written when no terminal-verdict policy was evaluated (D10) (#265)
- `docker/e2e/run_in_image_adversarial.sh`: bumped `pytest==9.0.3` → `pytest==9.1.1` to match the `pyproject.toml` dev-dependency pin; one pytest version now spans unit CI and the adversarial image run (#271)
- `mcp/git`: `commit_changes` no longer attempts a doomed Git Data API `PATCH /git/refs/heads/{branch}` after a local commit; every return path now includes `pushed: false` so callers do not need a defensive `.get("pushed")` (#259)
- `analyzers/parsers/osv_json`: escaped the unescaped middle dot in the `_fixed_version` regex (`r"\d+\.\d+.\d+"` → `r"\d+\.\d+\.\d+"`); the bare `.` wildcard let two-component versions with three or more digits after the decimal (e.g. `1.234`) be accepted as `N.N.N` — with the wildcard consuming the adjacent digit — producing a fabricated fix-version string handed verbatim to the reviewer as `Upgrade to 1.234 or later` (#270)
- `analyzers/scope.base_comparison_available`: corrected inverted return — findings on an online `baseComparison: full` run were attributed as if the base comparison had not happened (all `introduced_by_pr` left `"unknown"`), while findings on an offline run were falsely attributed as introduced-by-PR; now returns `not offline` so that attribution is correct in both directions (#269)
- `mcp/git`: corrected `commit_changes` tool description — it performs a local commit only and does not push to the remote or produce a GitHub-verified commit (#259)
- `mcp/git`: `--namespace` is now refused outright rather than forwarded. It was the one extracted global option with no validation, and it cannot be path-confined because it sets `GIT_NAMESPACE`, a ref-namespace prefix rather than a path; no subcommand on the read-only allowlist consumes it (only `upload-pack` / `receive-pack` / `upload-archive` do), so refusal costs the reviewer no capability (#257)
- `mcp/git`: genuinely read-only invocations were refused, because a flat short-flag blocklist cannot express that a letter means different things to different subcommands — `git ls-files -o` / `-c` / `-co`, `git log -c`, `git show -c`, `git branch -av` / `-ar` / `-vvv`, `git branch --list <pattern>`, and `git diff -C`, which was mistaken for git's chdir option and swallowed the following token as its directory. Short flags are now read against the subcommand that defines them, `-C` after a subcommand that owns it is left in place, and a positional argument to `git branch --list` is understood as the glob it is. Every write vector stays refused (#257)
- `analyzers/adapters._run_ruff_format_check`: ruff format findings now cite the actual file that would reformat instead of always citing the first scoped file; with multiple files in a single `ruff format --check` invocation the reviewer was previously pointed at a file that was already correctly formatted (#268)
- `analyzers/adapters._run_ruff_format_check`: corrected the fallback finding message for a ruff invocation failure; when `ruff format --check` exits non-zero with no parseable `Would reformat:` line (a crash, syntax error, or unexpected output), the finding now reports `"ruff format check failed: analyzer produced no parseable output"` instead of falsely claiming the attributed file would be reformatted
- `analyzers/adapters._run_ruff_format_check`: on any repo running ruff 0.16 or newer every formatting finding disappeared and a clean run was mislabelled `"analyzer produced no parseable output"` — 0.16 routes `format --check` through the diagnostic renderer and no longer prints `Would reformat: <path>`; both output spellings are now parsed, ANSI colouring is stripped, and paths are taken only from `unformatted:` headers so an `invalid-syntax:` diagnostic is not read as an unformatted file. A sandbox refusal, or a ruff too old to support `format --check` at all, is now reported as a skipped analyzer rather than as a finding (#268)
- `analyzers/adapters._run_ruff_format_check`: a ruff `unformatted:` header with no location line of its own adopted a *later* diagnostic's location, so a reformat was attributed to a file that did not need one, and a location whose trailing `:line:col` did not parse was taken whole as a path and became a finding against a file that does not exist; a header now claims only the location on the line immediately following it, and an unparseable location yields no path at all (#268)
- Fixed `mergecraft review --format jsonl|sarif` writing empty output files and exiting 0 even with blockers — the CLI now threads a structured-findings sink through to the review so jsonl/sarif writers see real findings (#242 / `mergecraft-finding:v1:3f363546e98dad517048b8b9`)
- Fixed the empty-diff early return in `run_offline_diff_review` silently reporting `RunOutcome.passed` when `apply_diff_line_budget` fully truncated (or untrusted-path filtering emptied) the diff; the run now applies the scope-reduction downgrade and reports `inconclusive` (D12) (#242 / `mergecraft-finding:v1:2e1cb9c2153087658c3481bd`)
- Fixed `mergecraft review` default text mode never producing exit codes 10/11 — the CLI now requests structured findings internally so a CI script running `review` can block on the documented exit-code contract (#242 / `mergecraft-finding:v1:7a3cdf5ef1994610113e8e37`)
- Fixed `mergecraft plan` reporting `diff_path` that pointed at a path inside a torn-down `TemporaryDirectory`; the materialized diff is now persisted to `<repo>/.mergecraft/plan-review.diff` so the report's `diff_path` is reachable after return (#242 / `mergecraft-finding:v1:e8bc195570ae6f1cc8ab5bc6`)
- Fixed tool-call budget exhaustion only surfacing as a JSON-RPC error to the agent — `BudgetTracker` now records the `BudgetExhausted` it raises (`last_exhausted`) and `main._finalize` drains the tracker at finalize time, so a run that exhausts its tool-call budget is tagged `inconclusive` rather than approving on a partial signal (D12) (#242 / `mergecraft-finding:v1:aeb5d964c1d35e5a41784ded`)
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
- Fixed: a review run that completes without submitting a terminal verdict now reports `inconclusive` (a `neutral` check conclusion) instead of `passed`. Previously a provider that returned successfully without reviewing anything produced a successful run. Prose such as "LGTM" has never been able to approve and still cannot
- `submit_review_verdict` now rejects non-list `findings` and severities outside
  the review taxonomy, hashes the validated payload so omitting `findings` matches
  `findings: []`, keeps a conflict flag sticky for the attempt, and scopes the
  recorded submit to the active model-chain attempt so a fallback cannot inherit
  or conflict-reject the failed attempt's verdict
- `README.md`'s CLI table documented `mergecraft traces <run-id>`, but the real
  registered command is `mergecraft traces show <run-id>` — the stale
  invocation is now generated from the live CLI app instead of hand-maintained
- `tracing_logfire_wf_yaml` `uses_re` regex now matches the inline
  `- uses: alexhawat/mergeCraft@X` step form (used by README Examples 1 and
  6) — previously the regex required leading whitespace before `uses:` and
  silently rejected every workflow the README documents. The `_do` closure
  now also synthesises a `with:` block when absent (symmetric with
  `_create_env_block`) — every `action.yml` input is `required: false`, and
  the comment claiming otherwise was wrong

### Security

- Mutating MCP tools other than review-session verbs (`select_mode`, checkout, review publication) are refused unless a write-capable mode is selected, including before mode selection (#350)
- GitLab webhook `X-Gitlab-Token` is compared as a shared secret, not an HMAC of the body; missing delivery ids fail closed instead of accepting anonymous (#361)
- External URL retrieval also blocks decimal, hex, and short IPv4 forms, IPv6-mapped loopback, and DNS that resolves to loopback, link-local, or metadata; DNS failure is fail-closed (#362)
- Dependency and container-image vulnerability gates no longer report a pass without running a scanner (#362)
- Network egress is allow-listed (`allow_egress`), external retrieval refuses SSRF targets (loopback, link-local metadata, `file:`), dependency and container-image vulnerability gates are invocable and the image gate is not `make security`, public comments redact secret tokens, and `docs/THREAT-MODEL.md` ties those controls to `tests/security/test_cd_egress.py` plus an independent security review before a stable release (#362)
- GitHub webhook deliveries require a matching HMAC; GitLab uses shared-secret `X-Gitlab-Token`; stale or reused deliveries are rejected and each delivery id is processed once; a provider 429 is retried instead of dropped, and webhook adapters still cannot commit, push, or edit (#361)
- `SECURITY.md` states the review-only guarantee: identify, investigate, verify, explain, prioritize, and suggest; no source edits, applied fixes, commits, pushes, or code-changing pull requests (#350)
- Review runs are review-only: `Fix`, `Build`, `Task`, `AddressReviews`, and `ResolveConflicts` are no longer selectable, and a Review or IncrementalReview run cannot edit the workspace, commit, push, or open a code-changing PR. Illustrative diffs stay GitHub suggestion comments (#350)
- `mergecraft mcp serve` now mints a per-serve Bearer token and requires it on every MCP request; unauthenticated `tools/list` and `tools/call` are rejected with HTTP 401 / JSON-RPC `-32600` (#345). `build_mcp_tool_context` mints the token via `secrets.token_hex(32)`, stores it as `ctx.mcp_auth_token`, and passes it as `auth_token=` into `create_mcp_app`; the token is printed to stderr as `MERGECRAFT_MCP_BEARER=<token>` at startup.
- `mcp/server`: primary `/mcp/reviewer` now admits session tools `set_output`, `select_mode`, and `report_progress` via `PRIMARY_MUTATING_ALLOWLIST`; routing the primary agent to `/mcp/reviewer` no longer drops tools required by the Action output schema, the mode-selection playbook (Step 1), and the no-action path. Repo mutations (`push_branch`, `commit_changes`, etc.) and review-write tools not in the allowlist (`resolve_review_thread`) stay off the reviewer surface; subagents continue to use the narrower `READONLY_MUTATING_ALLOWLIST`
- docs: `SECURITY.md` secret-stripping claim narrowed to the agent subprocess (`build_agent_env` / `filter_env`) and the sandboxed `shell` tool (`resolve_env`); `_run_git` inherits the process environment and is not covered by the filter (#286)
- Untrusted PR trees no longer receive a `shell` tool when PID-namespace isolation is unavailable (#287)
- Untrusted PR trees no longer run package install lifecycle scripts in the Action process when `shell` is the default `restricted` (#284)
- `mcp/git`: replaced permissive `_SUBCOMMAND_RE` with an explicit read-only allowlist (`status`, `log`, `diff`, `show`, `rev-parse`, `describe`, `ls-files`, `blame`, `cat-file`, `rev-list`, read-only `branch`); `git reset`, `git clean`, `git stash`, and all other mutating subcommands now raise `ValueError` unconditionally (#257)
- `mcp/git`: `-c` / `--config-env` are now rejected unconditionally regardless of `payload.shell`, closing the `git -c alias.x='!cmd'` arbitrary-shell-execution vector that bypassed the former `shell: disabled` guard (#257)
- `mcp/git`: the glued single-token spelling (`-ckey=value`) is refused alongside the spaced and inline forms, so the alias-execution block no longer depends on how the flag was written. The `-c`-shaped token is read against the short flags the subcommand defines before it is judged, which keeps `ls-files -co` and `log -c` working — a glued config payload cannot pass that test, because a key name, a `.` and an `=` are not short-flag letters (#257)
- `mcp/git`: `git branch` write forms reached refs through a tool declared repository-*read* — only `-d` / `-D` / `-m` were blocked, leaving `--delete`, `--move`, `-M`, `--copy` and bare `git branch <name>` creation to succeed. Listing flags are now an allowlist rather than a list of remembered write spellings, bundled and repeated short flags are checked letter by letter so one write letter refuses the whole token, and a rename of the checked-out branch can no longer change what a later `commit_changes` or `push_branch` targets (#257)
- `mcp/git`: `git diff --output=<path>` wrote an arbitrary file through a read-only tool — the subcommand allowlist constrains the verb, not the flags the verb accepts. `--output` and every unambiguous prefix git also honours (`--out`, `--outp`, …) are refused on every allowlisted subcommand, and `-o` is refused on the subcommands that do not define it themselves (#257)
- `mcp/shell`: a `git` invocation on its own line was never inspected, because the guard's separator class omitted the newline while `bash -c` runs every line of its argument — so `git -c alias.z='!sh …'` reached the shell and bypassed the git tool's alias block along with the `clean` and `filter-branch` verbs that tool refuses by name. Every command position in the command string is now scanned, across newlines, command substitution and backticks; git is matched by path basename so `/usr/bin/git` and the alias-suppressing `\git` are seen; and leading environment assignments, a wrapper's own numeric or path argument, and wrapper commands (`env`, `xargs`, `timeout`, `sudo`, `flock`, `script`, nested `sh -c`, and others) are looked past. `grep git README` and `ls .git` still run. This stays defence in depth behind the git tools' own allowlist, not a shell parser — arbitrarily quoted payloads, variable indirection and `printf … | sh` remain out of reach of any token scan (#257)
- `mcp/git`: `-C`, `--git-dir`, and `--work-tree` are now confined to the resolved primary repo root; any path outside raises `ValueError` with the offending path in the message (#257)
- `mcp/upload`: `upload_file` now rejects symlinks and confines the requested path to the primary repo root or the session `tmpdir`; no `file://` URI is emitted for a path that fails confinement (#258)
- `mcp/labels`: label names are now percent-encoded (`urllib.parse.quote(label, safe="")`) before interpolation into the `DELETE /labels/{label}` path segment, preventing `/` or `..` in a label name from shifting the URL path (#260)
- `cli/auth`: credentials written by `mergecraft auth` inherited the umask, so a `.env` started from the documented `cp .env.example .env` stayed readable by every user on the machine while holding Codex OAuth JSON, Claude tokens and up to five provider API keys — the first path writing any of them outside a temporary directory. The file is narrowed to `0600` *before* the credential is written as well as after, so there is no window in which the secret sits in a world-readable file. A `chmod` that fails warns rather than refusing the write (#221)
- Linked-repo reads are grant-gated (D9): a run can only load repos declared in its authorized set; linked-repo and ticket text render through the W4 fence as untrusted data
- Discovered repo instruction and skill files (`CLAUDE.md`, `AGENTS.md`, `SKILL.md`, `.cursor/rules/*.md`) from an untrusted review source render through the W4 fence as evidence and never enter the instruction bundle
- CLI offline reviews now derive a trust tier from review-source provenance; cloned or out-of-root paths review at untrusted tier unless the operator passes an explicit `--trust` override
- Executable repo config (`setupScript`, `prepushScript`, `stopScript`, `staticChecks[].command`) from an untrusted review source is ignored; declarative config still applies
- Third-party clone acquisition is bounded and credential-safe: HTTPS GitHub URLs only, no redirect following, no submodule recursion by default, size and file-count ceilings, symlink/path containment, tokens never persisted in `.git/config` or process argv
- Added `mergecraft review` to target any local worktree, public GitHub repo, or private repo (with `--token` / `GH_TOKEN` / `gh auth token`), with `--head`, `--base`, `--staged`, `--unstaged`, and `--range` diff selection; `diff-review` remains as a hidden alias
- Reviewer and verifier now hold distinct, class-derived MCP toolsets; the live
  MCP server exposes those surfaces at `/mcp/reviewer` and `/mcp/verifier`,
  mutating tools stay off both except `checkout_pr` on the reviewer, and
  finding-verdict persistence stays orchestrator-only
- `AgentRunContext.mcp_server_url` now carries the role endpoint for the primary reviewer (`/mcp/reviewer`); `write_mcp_config` maps the current agent span to the role URL so the Claude verifier connects to `/mcp/verifier`, not the orchestrator surface (#282)
- `build_mcp_app_for_role` with `role="reviewer"` or `role="verifier"` no longer mounts the orchestrator toolset at `/mcp`; only the role-specific path is active (#282)
- Primary reviewer surface (`/mcp/reviewer`) now includes `create_pull_request_review` (`ToolClass.REVIEW_WRITE`) via `PRIMARY_REVIEWER_ALLOWED_TOOL_CLASSES` and `PRIMARY_MUTATING_ALLOWLIST`; subagents retain the narrower `REVIEWER_ALLOWED_TOOL_CLASSES` complement so they remain denied review publication (D9, #282)
- MCP HTTP server now issues a per-run secret at startup (`ToolContext.mcp_auth_token`); `tools/list` and `tools/call` reject unauthenticated requests with HTTP 401 / JSON-RPC `-32600`; the bearer token is wired into the harness MCP `headers` config for Claude, Gemini, OpenCode, and Cursor; Codex receives the token via `MERGECRAFT_MCP_TOKEN` and presents it through the documented `bearer_token_env_var` config key (D15/D16, #283)
- Port allocator replaced: `_select_port` now uses `bind((MCP_HOST, 0))` to let the OS pick an ephemeral port instead of scanning a fixed 50-wide band from 3764; `MERGECRAFT_MCP_PORT` override is preserved; `mergecraft doctor` reports "ephemeral port" instead of a fixed number (#283)
- `AgentRegistry.resolve_tool_names` and `_default_tool_classes` now align with `build_reviewer_tools`: reviewer binding uses `PRIMARY_REVIEWER_ALLOWED_TOOL_CLASSES` and `PRIMARY_MUTATING_ALLOWLIST`, so `create_pull_request_review` is correctly included in the registry-derived surface (D9, #282)
- `offline_review` now routes agents to `MCP_REVIEWER_ENDPOINT` (`/mcp/reviewer`) rather than the orchestrator `/mcp`; terminal-protocol and orchestrator-only tools are no longer reachable from offline CLI reviews (#282)

### Removed

## [0.1.0] — 2026-08-14

Initial public release: mergeCraft is a standalone, BYOK GitHub Action for
AI-powered PR review — no proprietary backend, no account, review runs
against your own Claude/Codex/Gemini subscription or API key.

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
