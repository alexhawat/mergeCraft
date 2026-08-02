# Contributing

## Setup

```bash
make setup
```

Requires Python 3.14 and [uv](https://docs.astral.sh/uv/).

## Checks

```bash
make lint
make typecheck
make test
make ci
```

## Commits

Use [Conventional Commits](https://www.conventionalcommits.org/): `feat:`, `fix:`,
`docs:`, `chore:`, `test:`, `ci:`, `refactor:`. Subject ≤ 72 characters.

## Layout

- `src/mergecraft/` — package (src layout)
- `tests/` — mirrors package areas
- `Makefile` — single command surface (sevn-style)
- Docker Action via root `Dockerfile` + `action.yml`

## Notes

- Application code uses **loguru** only (no stdlib `logging` outside `src/mergecraft/logging/`).
- This is a standalone BYOK port — do not add proprietary SaaS clients.

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

Add repository secrets for the Release workflow: `TWINE_USERNAME`, `TWINE_PASSWORD`.

### Cut a release

1. **Prepare** (creates `release/<version>`, bumps `pyproject.toml`, cuts `CHANGELOG.md`, pushes):
   ```bash
   craft prepare auto   # or: craft prepare 0.1.0
   ```
2. **CI/CD** on the release branch runs `make ci`, builds `dist/*`, uploads the
   `artifact-python-dist` artifact, and pushes SHA-tagged GHCR images.
3. **Publish** (waits for green CI, uploads to GitHub/PyPI/GHCR):
   ```bash
   craft publish <version>
   ```

Or dispatch **Release** in GitHub Actions (`.github/workflows/release.yml`) with
`version: auto` or an explicit semver.

Dry-run locally: `craft prepare auto --dry-run`.

The first release has no prior git tag — use an explicit version (e.g. `craft prepare 0.0.1`)
instead of `auto`. GitHub releases are created by Craft's `github` target during `publish`
(not the CI/CD workflow).

Changelog previews post on pull requests via `.github/workflows/changelog-preview.yml`.
Skip entries with `#skip-changelog` or the `skip-changelog` label.
