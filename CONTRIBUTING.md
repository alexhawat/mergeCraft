# Contributing

Contributor setup, make targets, and PR expectations for mergeCraft itself.

**Audience:** contributor

## Setup

```bash
make setup
```

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/) ([`docs/dev/python-version-floor.md`](docs/dev/python-version-floor.md)).

`make setup` and all Makefile targets use a dedicated project virtualenv at
`.venv-dev` (via `UV_PROJECT_ENVIRONMENT` in the Makefile). This keeps the dev
venv separate from the default `.venv` that `uv sync` would create at the repo
root, so subprocess test helpers that invoke `uv run` do not mutate the
environment the test runner itself is using (AG8 / MCB-23).

## Checks

```bash
make lint
make typecheck
make test
make ci
```

`make test` runs the unit and mocked-integration suite — **no API keys or secrets required**.
Live-provider tests are excluded by default (`-m "not integration"`).

`make coverage-gate` enforces the native coverage.py combined line-and-branch
``fail_under`` floor on every CI event. Critical module and package-prefix
floors separately enforce pure line coverage from line counts and branch
coverage from branch counts. The merge-base **lowering guard** that blocks
undeclared ``fail_under`` drops runs only on pull requests, because on ``push``
/ ``workflow_dispatch`` the merge-base comparison is self-referential.

### Config path resolution (#573)

``load_repo_settings()`` resolves ``.mergecraft/config.yaml`` through this
ladder (first hit wins):

1. explicit ``root=`` argument
2. ``MERGECRAFT_CONFIG`` when the file exists
3. ``<workspace-root>/.mergecraft/config.yaml``

**Workspace root** (the base for step 3 when no explicit path is set):

| Situation | Root used |
|-----------|-----------|
| No ``GITHUB_WORKSPACE`` | process ``cwd`` |
| ``cwd`` inside ``GITHUB_WORKSPACE`` (normal CI) | ``GITHUB_WORKSPACE`` |
| ``cwd`` in a **sibling git worktree** of the same repo | the **cwd** worktree (#573) |
| otherwise | ``GITHUB_WORKSPACE`` |

The coverage gate's base measurement runs inside a detached worktree and
**re-exports ``GITHUB_WORKSPACE`` at that worktree** before calling
``make coverage-measure``. Each tree therefore reads its own config even
when Actions still has the PR checkout as the outer workspace.

### Coverage gate contract (#432 / #536)

On ``pull_request``, ``scripts/ci_coverage_delta_gate.sh``:

1. measures coverage on the merge-base worktree (signal only)
2. runs ``make coverage-gate`` on the **PR checkout** (hard gate — always)
3. compares head vs base when ``coverage-base.json`` exists

| Step | On failure |
|------|------------|
| Base measurement | **No** ``coverage-base.json``; delta **skipped** with an Actions ``::warning::`` and a job-summary line naming ``GITHUB_BASE_REF`` and the reason |
| Head ``make coverage-gate`` | Run **fails** — the ratchet stays on |
| Delta comparison | Runs only when base measurement succeeded |

On ``push`` / ``workflow_dispatch`` the script runs the head gate only (no
merge-base worktree).

### Coverage shards

The default `make coverage-measure` and `make coverage-gate` remain complete,
unsharded runs. To diagnose one isolated shard, give it a split count and group:

```bash
MERGECRAFT_TEST_SPLITS=2 MERGECRAFT_TEST_GROUP=1 make coverage-measure
```

The command prints its unique artifact directory. Run every group with the same
explicit directory, then validate the manifests, combine the raw databases, and
apply the complete coverage gates:

```bash
MERGECRAFT_TEST_SPLITS=2 MERGECRAFT_TEST_GROUP=1 MERGECRAFT_COVERAGE_RUN_DIR=/tmp/mergecraft-cov make coverage-measure
MERGECRAFT_TEST_SPLITS=2 MERGECRAFT_TEST_GROUP=2 MERGECRAFT_COVERAGE_RUN_DIR=/tmp/mergecraft-cov make coverage-measure
MERGECRAFT_TEST_SPLITS=2 MERGECRAFT_COVERAGE_RUN_DIR=/tmp/mergecraft-cov make coverage-combine-gate
```

For one atomic CI stage, set only the split count. The gate runs bounded groups,
validates their exact test collection, combines them, and enforces all floors:

```bash
MERGECRAFT_TEST_SPLITS=2 make coverage-gate
MERGECRAFT_TEST_SPLITS=2 make ci-resume
```

A partial shard never writes `coverage.json` or invokes a floor. Missing,
overlapping, modified, stale, or incompatible manifests fail before combination.

### Live slice

The scheduled Integration workflow's live-provider matrix runs the one leg
this repository can authenticate: `github` (`GITHUB_TOKEN`). The `anthropic`, `openai` and `gemini` HTTP-API legs are
**not exercised** — no Anthropic, OpenAI or Gemini API key is configured, and a
subscription cannot call those HTTP endpoints. Real-harness live coverage runs
as the nightly E2E live slice on the provider named by
`vars.MERGECRAFT_E2E_LIVE_MODEL` (OpenCode Go, secret `OPENCODE_GO_API_KEY`). It
no longer consumes the ChatGPT/Codex subscription, so it cannot retire the
self-review's session.

### Decision record: the Codex subscription credential (#970)

`CODEX_AUTH_JSON` holds a ChatGPT-subscription login. Codex refreshes it while it
is in use and retires the previous refresh token, so any consumer that refreshes
it spends the copy stored in the secret, and nothing writes the new one back. The
next run that needs a refresh fails with "refresh token was already used" until
someone re-authenticates.

What is decided and shipped:

- The nightly E2E live slice moved to OpenCode Go (#975). It does not touch the
  subscription.
- The self-review's first rung is OpenCode Go (#988). The Codex subscription rung
  is a fallback, not the primary reviewer.
- Every job that receives `CODEX_AUTH_JSON` joins the `codex-subscription-auth`
  concurrency group with `cancel-in-progress: false`, so two consumers never
  refresh the same login at once (#882). GitHub keeps one running and one pending
  job per group; a third queued review replaces the pending one and needs a re-run.
- An expired credential is named instead of buried in a log: the run ends as
  `infra_error` with *reviewer credential expired — re-authenticate*, in the check
  summary and the run record (#922).
- There is **no scheduled canary**. Exercising the credential on a schedule
  refreshes it and spends the stored refresh token, which is the failure being
  prevented.

What is still open (the issue stays open until the maintainer chooses):

| Option | What it buys | What it costs |
| --- | --- | --- |
| Run the OpenAI rung on an API key | No rotating credential in CI at all | A paid key, and a different billing path from the subscription |
| Write the refreshed credential back to the secret after each run | The stored copy never goes stale | A token allowed to write repository secrets inside a review job: a significant permission to hand a job that runs on pull-request content |
| Hold and refresh the login in one place outside CI (a small broker), CI receiving only short-lived access tokens | The subscription stays in use and nothing in CI can spend it | A service to run, secure and keep available |

**Recommendation:** keep the subscription out of review-job secret writes — no
write-back token, ever. Revisit a broker only if the Codex fallback rung becomes
load-bearing. Until then the cost of the credential dying is one named, recoverable
infrastructure outcome on a rung that is not the primary reviewer.

To recover when the credential is retired, re-mint it locally and store it:

```bash
mergecraft auth codex
gh secret set CODEX_AUTH_JSON
```

To run the live slice locally (requires the matching provider secret):

```bash
MERGECRAFT_LIVE=1 make test-integration-live
```

`MERGECRAFT_LIVE=1` is the opt-in gate: without it, the live modules skip
collection. With the flag set but secrets absent the suite still fails loudly
(fail-closed).

## Operator: branch protection

The **CI/CD** workflow (`.github/workflows/ci-cd.yml`) must be a **required status
check** on `main` and `pre-0.0.1`. A workflow that fails at startup
(``startup_failure``) — for example when a ``uses:`` job does not grant the
permissions its called workflow declares — produces no logs, annotations, or check
runs (#425). Requiring CI/CD makes that silence block merges. Apply this in GitHub
branch protection; this repository does not configure it automatically.

`make lint` now includes ``scripts/check_called_workflow_permissions.py`` to catch
the permissions mismatch at authoring time.

## Commits

Use [Conventional Commits](https://www.conventionalcommits.org/): `feat:`, `fix:`,
`docs:`, `chore:`, `test:`, `ci:`, `refactor:`. Subject ≤ 72 characters.

## Layout

- `src/mergecraft/` — package (src layout)
- `tests/` — mirrors package areas
- `tests/harness/` — deterministic provider-harness RED/GREEN suites (no live API keys on `make test`)
- `Makefile` — single command surface (sevn-style)
- Docker Action via root `Dockerfile` + `action.yml`

## Notes

- Application code uses **loguru** only (no stdlib `logging` outside `src/mergecraft/logging/`).
- This is a standalone BYOK port — do not add proprietary SaaS clients.
- Config-failure policy: security/runtime settings fail closed;
  optional features warn-and-disable. See [`docs/config-failure-policy.md`](docs/config-failure-policy.md).

## Naming (S1)

| Surface | Spelling |
|---------|----------|
| GitHub repo | `mergeCraft` (camelCase) |
| Python package / import | `mergecraft` (lowercase) |
| CLI binary | `mergecraft` (not `mc` — Midnight Commander collision) |
| PyPI distribution | `merge-craft` (published via [Craft](https://github.com/getsentry/craft)) |
| Container image | `ghcr.io/alexhawat/mergecraft` (lowercase, hardcoded) |
| MCP server | `mergecraft` → `mcp__mergecraft__*` / `mergecraft_*` |
| Config directory | `.mergecraft/` |

Never interchange repo spelling with package spelling in code.

## Releases (Craft)

Releases are managed with [Sentry Craft](https://github.com/getsentry/craft). Configuration
lives in `.craft.yml` at the repo root.

### Prerequisites

- Craft CLI: `npm install -g @sentry/craft` (or download a [binary release](https://github.com/getsentry/craft/releases))
- `GITHUB_TOKEN` with `repo` scope (local prepare/publish, or supplied by Actions)
- PyPI credentials for publish: `TWINE_USERNAME` and `TWINE_PASSWORD` (or API token as password)

Add repository secrets for Craft publish: `TWINE_USERNAME`, `TWINE_PASSWORD`.

### Cut a release

1. **Prepare** (creates `release/<version>`, bumps `pyproject.toml` and `server.json`, cuts `CHANGELOG.md`, pushes):
   ```bash
   craft prepare auto   # or: craft prepare 0.1.0
   ```
2. **CI/CD** on the release branch (build-once → promote digest):
   - runs `make ci`
   - builds `dist/*`, install-checks the wheel with `make test-wheel-corpus`, and
     attaches build provenance before uploading `artifact-python-dist`
   - builds each GHCR image **once**, pushes immutable `:${GITHUB_SHA}` /
     `:analyzers-${GITHUB_SHA}` tags, and captures the digests
   - generates an SBOM (syft) + Trivy scan per image (CRITICAL/HIGH gate on
     `release/**` and `v*` tags); uploads `image-scan-reports`
   - cosign keyless-signs both digests and attaches build-provenance + SBOM
     attestations
   - on `main`, promotes `:latest` / `:analyzers` by **retagging the same
     digests** (no second rebuild); on `pre-0.0.1`, promotes to `:rc` /
     `:analyzers-rc` instead, so a pre-release build can never win the
     `:latest` / `:analyzers` tags just by finishing later

**Release preconditions** (must be green or an explicit documented skip before
`craft publish`):

- Scheduled **Integration** workflow live-provider job
  (`.github/workflows/integration.yml` → `make test-integration-live`) with at
  least one provider secret present
- Scheduled **E2E** nightly security slice (`.github/workflows/e2e.yml`)
- Image SBOM + Trivy CRITICAL/HIGH gate on the release branch

Local mirrors: `make test-integration`, `make test-integration-live`,
`make coverage-gate`, `make npm-audit`, `make workflow-lint`.

3. **Publish** (Craft retags the signed SHA digests → version / latest tags via
   `.craft.yml`, then uploads to GitHub/PyPI):
   ```bash
   craft publish <version>
   ```

Or dispatch **Release** in GitHub Actions (`.github/workflows/release.yml`) with
`version: auto` or an explicit semver. That workflow only prepares the release
branch (least-privilege jobs; no `secrets: inherit`); image signing stays in
CI/CD.

Dry-run locally: `craft prepare auto --dry-run`.

The first release has no prior git tag — use an explicit version (e.g. `craft prepare 0.0.1`)
instead of `auto`. GitHub releases are created by Craft's `github` target during `publish`
(not the CI/CD workflow).

Changelog previews post on pull requests via `.github/workflows/changelog-preview.yml`.
Skip entries with `#skip-changelog` or the `skip-changelog` label.

### Verify a published image

For the exact consumer `uses:` pin, run `make action-image-digest-check`.
It reads the pinned commit’s manifest and verifies its signed image against
the built source, rather than comparing the working tree to a mutable tag.
The two-phase preparation flow is documented in
[Action manifest and consumer pin lifecycle](docs/release-process.md#action-manifest-and-consumer-pin-lifecycle).


Replace `<digest>` with the digest from the CI/CD run (or `crane digest
ghcr.io/alexhawat/mergecraft:<tag>`):

```bash
# Cosign keyless signature (Sigstore)
cosign verify \
  --certificate-identity-regexp='https://github.com/alexhawat/mergeCraft/' \
  --certificate-oidc-issuer=https://token.actions.githubusercontent.com \
  ghcr.io/alexhawat/mergecraft@sha256:<digest>

# GitHub build-provenance attestation
gh attestation verify \
  oci://ghcr.io/alexhawat/mergecraft@sha256:<digest> \
  --owner alexhawat

# SBOM attestation (when attached)
gh attestation verify \
  oci://ghcr.io/alexhawat/mergecraft@sha256:<digest> \
  --owner alexhawat \
  --predicate-type https://spdx.dev/Document
```

SBOM and Trivy SARIF reports are attached to the CI/CD run as the
`image-scan-reports` artifact.

## See also

- [docs/README.md](docs/README.md) — generated documentation index
- [REVIEW-CHECKS.md](REVIEW-CHECKS.md) — review checks mergeCraft applies on PRs
- [Landing README](README.md) — consumer install and feature overview
