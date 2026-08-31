# Contributing

Contributor setup, make targets, and PR expectations for mergeCraft itself.

**Audience:** contributor

## Setup

```bash
make setup
```

Requires Python 3.14 and [uv](https://docs.astral.sh/uv/).

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

`make coverage-gate` enforces the ``fail_under`` floor on every CI event; the
merge-base **lowering guard** that blocks undeclared ``fail_under`` drops runs
only on pull requests, because on ``push`` / ``workflow_dispatch`` the
merge-base comparison is self-referential.

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
| ``cwd`` in a **sibling git worktree** of the same repo | the **cwd** worktree (#573 / D2) |
| otherwise | ``GITHUB_WORKSPACE`` |

The coverage gate's base measurement runs inside a detached worktree and
**re-exports ``GITHUB_WORKSPACE`` at that worktree** before calling
``make coverage-measure`` (D1). Each tree therefore reads its own config even
when Actions still has the PR checkout as the outer workspace.

### Coverage gate contract (#432 / #536)

On ``pull_request``, ``scripts/ci_coverage_delta_gate.sh``:

1. measures coverage on the merge-base worktree (signal only)
2. runs ``make coverage-gate`` on the **PR checkout** (hard gate — always)
3. compares head vs base when ``coverage-base.json`` exists

| Step | On failure |
|------|------------|
| Base measurement | **No** ``coverage-base.json``; delta **skipped** with an Actions ``::warning::`` and a job-summary line naming ``GITHUB_BASE_REF`` and the reason (D4/D6) |
| Head ``make coverage-gate`` | Run **fails** — the ratchet stays on (D5) |
| Delta comparison | Runs only when base measurement succeeded |

On ``push`` / ``workflow_dispatch`` the script runs the head gate only (no
merge-base worktree).

To run the live slice (requires provider secrets such as `ANTHROPIC_API_KEY`):

```bash
MERGECRAFT_LIVE=1 make test-integration-live
```

`MERGECRAFT_LIVE=1` is the opt-in gate: without it, the live modules skip collection.
With the flag set but secrets absent the suite still fails loudly (D9 — fail-closed).

## Operator: branch protection

The **CI/CD** workflow (`.github/workflows/ci-cd.yml`) must be a **required status
check** on `main` and `pre-0.0.1`. A workflow that fails at startup
(``startup_failure``) — for example when a ``uses:`` job does not grant the
permissions its called workflow declares — produces no logs, annotations, or check
runs (#425). Requiring CI/CD makes that silence block merges. Apply this in GitHub
branch protection; this repository does not configure it automatically.

`make lint` now includes ``scripts/check_called_workflow_permissions.py`` to catch
the permissions mismatch at authoring time (D5).

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
- Config-failure policy (D4): security/runtime settings fail closed;
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

1. **Prepare** (creates `release/<version>`, bumps `pyproject.toml`, cuts `CHANGELOG.md`, pushes):
   ```bash
   craft prepare auto   # or: craft prepare 0.1.0
   ```
2. **CI/CD** on the release branch (build-once → promote digest):
   - runs `make ci`
   - builds `dist/*` and uploads `artifact-python-dist`
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
