# Analyzer catalog

Shipped mergeCraft catalog analyzers. Rows are generated from manifests — run ``uv run python -m mergecraft.analyzers.catalog_docs`` to refresh.


> **Provider configuration (catalog slugs, credential detection, `mergecraft auth <provider>`) is documented in [Authentication](../docs/authentication.md).** This page is the *analyzer* catalog — the rows below are deterministic, manifest-driven tools (`actionlint`, `zizmor`, `ShellCheck`, `Hadolint`, …) the reviewer runs mechanically. The Nous Research / DeepSeek V4 Flash path (provider id `nous`, catalog slug `nous/deepseek/deepseek-v4-flash`) is a *provider*, not an analyzer, and lives in the README's [Authentication table](../docs/authentication.md) alongside Anthropic, OpenAI, Google, and Cursor. Set up its secret with [`mergecraft auth nous`](../docs/authentication.md); see [issue #57](https://github.com/alexhawat/mergeCraft/issues/57) for the rationale.

| id | category | languages | default | runtime | trust | exclusive group | notes |
|----|----------|-----------|---------|---------|-------|-----------------|-------|
| `actionlint` | ci | — | auto | managed | untrusted | — | — |
| `agentsec` | security | — | enabled | repo-native | untrusted | — | — |
| `antislop` | quality | python, javascript, typescript | disabled | repo-native | trusted | — | — |
| `ast-grep` | security | python, javascript, typescript, go, java, rust, c, cpp, yaml | auto | managed | untrusted | pattern-scanner | Substrate for a future native policy engine — not built in C3. |
| `bandit` | security | python | auto | repo-native | trusted | — | — |
| `basedpyright` | lint | python | auto | repo-native | trusted | python-typecheck | — |
| `biome` | lint | javascript, typescript | auto | repo-native | trusted | js-lint | — |
| `blinter` | lint | batch | auto | managed | trusted | — | requires non-Linux runner — Windows batch lint not supported on Linux (C6) |
| `brakeman` | security | ruby | auto | repo-native | trusted | — | — |
| `buf` | contract | — | auto | managed | untrusted | — | — |
| `bundler-audit` | vuln | ruby | auto | repo-native | trusted | — | — |
| `cargo-audit` | vuln | rust | auto | repo-native | trusted | — | — |
| `cargo-deny` | license | rust | auto | repo-native | trusted | — | — |
| `checkmake` | lint | make | auto | managed | trusted | — | — |
| `checkov` | security | terraform, cloudformation | auto | managed | untrusted | — | manifest-only — checkov binary not bundled for linux-amd64 (provisioning gap; use repo-native install or wait for pinned provenance) |
| `circleci` | lint | yaml | disabled | managed | untrusted | — | — |
| `clang-tidy` | lint | c, cpp | disabled | container | trusted | — | requires compile_commands.json — mergeCraft never guesses compiler flags (C4) |
| `clippy` | lint | rust | auto | repo-native | trusted | rust-lint | — |
| `cppcheck` | lint | c, cpp | auto | managed | trusted | — | — |
| `detekt` | lint | kotlin | auto | repo-native | trusted | — | — |
| `dotenv-linter` | lint | — | disabled | managed | trusted | — | Values never printed in findings (D8). |
| `ember-template-lint` | lint | ember | auto | repo-native | trusted | — | — |
| `eslint` | lint | javascript, typescript | auto | repo-native | trusted | js-lint | — |
| `flake8` | lint | python | disabled | repo-native | trusted | python-lint | Legacy opt-in — disabled by default; enable via config override. |
| `fortitude` | lint | fortran | auto | managed | trusted | — | manifest-only — Fortitude not bundled on Linux runners (C6 out of scope) |
| `golangci-lint` | lint | go | auto | managed | trusted | go-lint | — |
| `govulncheck` | vuln | go | auto | repo-native | trusted | — | — |
| `hadolint` | lint | docker | auto | managed | untrusted | — | — |
| `htmlhint` | lint | html | auto | repo-native | trusted | — | — |
| `infer` | security | java, c, cpp | disabled | container | trusted | — | requires compilation database and build — container-only heavyweight (C4) |
| `jscpd` | quality | javascript, typescript, python | auto | repo-native | trusted | — | — |
| `knip` | quality | javascript, typescript | auto | repo-native | trusted | — | — |
| `languagetool` | lint | text | disabled | container | trusted | — | manifest-only — LanguageTool runtime not bundled on Linux runners (C6 out of scope) |
| `luacheck` | lint | lua | auto | repo-native | trusted | — | — |
| `markdownlint` | lint | markdown | auto | repo-native | trusted | — | — |
| `mypy` | lint | python | auto | repo-native | trusted | python-typecheck | — |
| `oasdiff` | contract | — | auto | managed | untrusted | — | — |
| `opengrep` | security | python, javascript, typescript, go, java, ruby, rust, yaml | disabled | managed | untrusted | pattern-scanner | — |
| `osv-scanner` | vuln | — | auto | managed | untrusted | dependency-vuln | — |
| `oxlint` | lint | javascript, typescript | auto | repo-native | trusted | js-lint | — |
| `phpcs` | lint | php | disabled | repo-native | trusted | php-lint | Legacy opt-in — disabled by default; phpstan is the default PHP signal. |
| `phpmd` | lint | php | disabled | repo-native | trusted | — | Legacy opt-in — disabled by default; phpstan is the default PHP signal. |
| `phpstan` | lint | php | auto | repo-native | trusted | — | No phpstan.neon/neon.dist → runs at --level=0 (D12). |
| `pmd` | lint | java | auto | managed | trusted | — | — |
| `presidio` | security | — | disabled | container | trusted | — | Container-only; high-confidence entity types only. |
| `prisma-lint` | lint | prisma | auto | repo-native | trusted | — | — |
| `psscriptanalyzer` | lint | powershell | auto | managed | trusted | — | requires non-Linux runner — Windows/macOS only (C6 out of scope) |
| `pylint` | lint | python | disabled | managed | trusted | python-lint | Legacy opt-in — disabled by default; enable via config override. |
| `pyright` | lint | python | auto | repo-native | trusted | python-typecheck | — |
| `regal` | lint | rego | auto | managed | trusted | — | — |
| `rubocop` | lint | ruby | auto | repo-native | trusted | ruby-lint | — |
| `ruff` | lint | python | auto | repo-native | trusted | python-lint | — |
| `semgrep` | security | python, javascript, typescript, go, java, ruby, rust, yaml | enabled | managed | untrusted | pattern-scanner | — |
| `shellcheck` | lint | shell | auto | managed | untrusted | — | — |
| `shopify-theme-check` | lint | liquid | auto | repo-native | trusted | — | manifest-only — Shopify Theme Check not bundled on Linux runners (C6 out of scope) |
| `smarty-lint` | lint | smarty | auto | repo-native | trusted | — | manifest-only — Smarty Lint not bundled on Linux runners (C6 out of scope) *.tpl extension is ambiguous (Go templates, Terraform, Smarty) — enable only when .smarty-lint.json confirms Smarty intent. |
| `sqlfluff` | lint | sql | auto | managed | trusted | — | Dialect is mandatory — skip when repo declares none. |
| `squawk` | migration | — | auto | managed | untrusted | — | — |
| `stylelint` | lint | css | auto | repo-native | trusted | — | — |
| `swiftlint` | lint | swift | auto | managed | trusted | — | requires non-Linux runner — SwiftLint needs macOS (C6 out of scope) |
| `tflint` | lint | terraform | auto | managed | untrusted | — | — |
| `trivy` | vuln | — | auto | managed | untrusted | dependency-vuln | — |
| `trufflehog` | secrets | — | auto | managed | untrusted | — | verify off by default; impossible on fork PRs (C2). |
| `tsc` | lint | typescript | auto | repo-native | trusted | — | — |
| `typos` | lint | python, javascript, typescript, rust, go, markdown | auto | repo-native | trusted | — | — |
| `vulture` | quality | python | auto | repo-native | trusted | — | — |
| `yamllint` | lint | yaml | auto | managed | untrusted | — | manifest-only — yamllint binary not bundled for linux-amd64 (provisioning gap; use repo-native install or wait for pinned provenance) |
| `zizmor` | ci | — | auto | managed | untrusted | — | — |

## Runtime x shell x trust x mode

Which analyzers run is decided on three independent axes. Each can skip a
manifest with a named reason — a skip is an outcome, never a failure, and it
appears as an `unavailable` row in the Analyzers pre-merge summary.

- **shell** (`shell:` in the workflow) — may mergeCraft execute anything the
  PR could have written? Enforced by `evaluate_manifest_for_shell()`.
- **trust** (derived from the event) — `pull_request_target` and fork-head PRs
  are `untrusted`. Enforced by `evaluate_manifest_for_tier()`.
- **mode** (`analyzers:` in the workflow) — `off | auto | full |
  untrusted-only`. Enforced by `evaluate_manifest_for_mode()` plus
  `resolve_selection_tier()`.

Under `shell: disabled`, eligible runtimes are `managed` and `container`.
Their argv is copied verbatim out of a manifest mergeCraft ships, and a binary
the repo provides may not stand in for the pinned one, so nothing the PR
authored is executed. `runtime: repo-native` stays withheld because it exists
to run the *repo's* tool against the *repo's* config.

| runtime | trust | `shell: disabled` | `shell: restricted` / `enabled` |
|---------|-------|-------------------|----------------------------------|
| `repo-native` (34) | `trusted` | withheld — `runtime` needs repo-provided tooling | runs on trusted events; skipped on untrusted |
| `repo-native` (1) | `untrusted` | withheld — `runtime` needs repo-provided tooling | runs |
| `managed` (12) | `trusted` | runs on trusted events; skipped with a reason on untrusted ones | runs on trusted events; skipped on untrusted |
| `managed` (17) | `untrusted` | **runs** (pinned binary only) | runs |
| `container` (4) | `trusted` | runs on trusted events; skipped with a reason on untrusted ones | runs on trusted events; skipped on untrusted |

One documented exception to the runtime row: `agentsec`, `antislop`. They declare
`runtime: repo-native` but `resolve_analyzer()` special-cases them before the
repo-binary preference is consulted and `run_adapter()` executes them
in-process — no subprocess, no argv, nothing the PR authored is run. The
runtime axis asks whether PR content could steer what executes; for these
the answer is no, so they stay eligible (#38).

`antislop` is `trust: trusted` and `default_enabled: false`. Enabling it via
`analyzers.overrides` on untrusted fork runs still no-ops when the trust axis
skips trusted-only analyzers — opt in only on trusted events.

### The `analyzers:` mode axis

`untrusted-only` runs only analyzers that need no secrets, no network and no
PR-authored command construction: manifest selection is evaluated at the
`untrusted` tier *and* the repo-tooling gate applies whatever the shell is.
On `pull_request_target` and fork-head pull requests, `auto` resolves to it
— a narrowing default, so a hardened workflow gets mechanical signal without
loosening `shell:`. An unrecognised `analyzers:` value resolves there too,
with a warning, rather than silently widening to `auto`.

`full` requests more provisioning; it is never a trust override, and cannot
re-admit a manifest the tier axis skipped.

Counts below are analyzers passing selection, out of 68 shipped, with
`shell: restricted` (the shell axis inert) so the mode axis is isolated.

| mode | trusted event | untrusted event (`pull_request_target`, fork) |
|------|---------------|-----------------------------------------------|
| **`off`** | surface not registered | surface not registered |
| **`auto`** | 68 of 68 | 18 of 68 — `auto` ⇒ `untrusted-only` |
| **`full`** | 68 of 68 | 18 of 68 |
| **`untrusted-only`** | 18 of 68 | 18 of 68 |

Passing these axes is necessary, not sufficient: a `container` manifest
is eligible but still reports `unavailable` wherever no container runtime is
present, and the seven `declared_unavailable` manifests keep their own skip
reason. In the shipped Action image that leaves the `managed` rows as the
analyzers a `shell: disabled` run actually executes.

Repo-declared `staticChecks` are a third thing and are **always** withheld
under `shell: disabled`, on every event: they run command strings the PR
author controls. They report `declared-but-cannot-run` rather than vanishing.
No `analyzers:` value re-enables them.

## Overrides

Enable or disable tools in ``.mergecraft/config.yaml``:

```yaml
analyzers:
  overrides:
    golangci-lint:
      enabled: true
```

See [CONTRIBUTING-ANALYZERS.md](CONTRIBUTING-ANALYZERS.md) to add a tool.

## Noise budget (D14)

Inline review comments from analyzers and the reviewing agent share a single cap of **8** slots (W0.2 measurement; configurable via `analyzers.inlineBudget`). Placement is deterministic:

- **Inline** — highest-priority findings up to the cap. Agent findings win tie-breaks over analyzer findings at the same severity and path.
- **Mechanical overflow** — `source: analyzer` / `source: ci` findings that did not earn an inline slot render as a compact `### 🔧 Mechanical findings` table (tool, rule id, path:line). mergeCraft appends this section server-side at publish time.
- **Deferred overflow** — `source: agent` findings that did not earn an inline slot render in `### 🗂 Deferred findings` with severity, path, line, and the **full finding body**. This lane is non-blocking (no inline anchor) and is also server-appended at publish time so overflow reasoning is never discarded.
- **Nitpicks** — `Trivial` severity or `Low value` effort never occupy inline or deferred slots; they belong in the Nitpicks section.

## Verification gate (D11)

`Critical` and `Major` findings are hypotheses until the read-only `mergecraft-verifier` subagent reads the cited code. That gate applies to analyzer, CI, and agent-authored findings.

Verification depth is **independent** of inline placement (`analyzers.inlineBudget`, default 8). The verifier dispatch cap is `review.verificationBudget` (default **24**). Set it to **`0`** to verify every eligible finding with no cap. Three filters run in order: severity (skip `Minor`/`Trivial`), withdrawn memory (skip fingerprints already refuted under `## Withdrawn review findings`), then the verification budget — so pre-budget skips never consume slots. Over-budget fingerprints surface in `skippedOverBudget` for the open-PR ledger (W3).

## Execution preference

For any given gate, in order — the first that can produce a verdict wins:

1. **`repo-native`** — the repo's own pinned toolchain, when this environment can run it.
2. **An existing CI result** — a check run the repo *declared* as proof of that gate (#36).
3. **A managed pinned binary**, then **a container**.
4. **Skip, with a named reason.** A skip is never a finding.

## CI evidence (#36)

The Action image usually lacks `make`, the repo's venv, and its pinned toolchains, so a repo-native gate reports `unavailable` even when the consumer's own CI just proved the same thing. Declaring the mapping lets that finished CI stand in:

```yaml
ciEvidence:
  gates:
    # <mergeCraft gate name>: <exact GitHub check-run name>
    lint: Verify (drift gates)
  sarifArtifacts:
    - ruff-sarif
```

- **Declared only.** mergeCraft never infers that a check run *named* `lint` proves the `lint` gate — a pull request can add a workflow with any name it likes. With no `ciEvidence` block nothing is read and no extra API call is made.
- **Green only substitutes.** A declared check run that passed rewrites the gate row to `satisfied-by-ci`. A declared check run that *failed* leaves the row alone and is reported as a `source: ci` finding instead.
- **Reported, not blamed.** Bare check-run findings start non-blocking; SARIF `error` from declared `sarifArtifacts` keeps Major/Critical. `introduced_by_pr` stays `unknown` until `ci/blame.py` / `ci/flaky.py` attribute a finding to this PR.
- **Redacted.** Log excerpts are truncated and passed through `analyzers/redact.py` before they enter a finding.

## SARIF upload to code scanning (#39)

Opt-in, off by default. When enabled, mergeCraft exports the analyzer findings of a pull-request run as SARIF 2.1.0 and uploads them to GitHub code scanning, so mechanical findings stay readable when the review narrative is thin or when findings overflowed the inline comment budget.

```yaml
# .github/workflows/mergecraft.yml
permissions:
  contents: read
  pull-requests: write
  # Required for the upload. Without it GitHub answers 403 and mergeCraft
  # logs a warning — the review still completes.
  security-events: write

jobs:
  review:
    steps:
      - uses: alexhawat/mergeCraft@<sha>
        with:
          sarif_upload: enabled
```

Or in `.mergecraft/config.yaml` (the action input wins when it is set):

```yaml
analyzers:
  sarifUpload: true
```

What is and is not uploaded:

- **Catalog analyzers only.** Only `source: analyzer` findings are eligible. `source: ci` findings carry truncated pipeline log excerpts and `source: agent` findings carry narrative; neither is uploaded, and raw logs never leave the process (D13).
- **The clustered, placed set.** The upload reuses the findings the pipeline already clustered and placed, not the raw analyzer output, so cross-tool duplicates arrive as one alert (D14). It is *not* truncated at the inline comment budget — the overflow is exactly what this surface exists to show.
- **Trust-gated.** Each finding's analyzer must still pass this run's `trust` x `shell` x `analyzers:` selection chain — the same predicates the pipeline calls, re-evaluated at upload time. A finding from a tool with no catalog manifest cannot be gated, so it is refused.
- **Redacted before serialization.** `message`, `evidence`, `remediation` and `autofix` pass through `analyzers/redact.py` while still typed `Finding`s, before SARIF is built. `path` is left intact: it becomes `artifactLocation.uri`, and mangling it would detach the alert from its file.
- **Never a gate.** A rejected upload — missing permission, code scanning unavailable, transport error — is logged at `warning` and the run continues.

Check-run annotations are the documented alternative surface and are not implemented: they need `checks: write` instead, cap at 50 annotations per request, and largely repeat the inline review comments mergeCraft already posts.
