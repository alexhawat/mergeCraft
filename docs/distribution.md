# 0.1.0 distribution checklist

Operator runbook for the agent-owned and operator-owned boxes in
[#141](https://github.com/alexhawat/mergeCraft/issues/141). Release gating
(E2E on publish SHA, blocking Trivy on promoting refs, live-provider matrix) is
documented in [`docs/supply-chain.md`](supply-chain.md) and the linked wave plan.

## Already shipped in CI (no operator publish step)

| Item | Evidence |
|------|----------|
| GHCR images (`mergecraft`, `mergecraft-analyzers`) | `.github/workflows/ci-cd.yml` `build-images` |
| Immutable `:${GITHUB_SHA}` / `:analyzers-${GITHUB_SHA}` tags | same job |
| `:latest` / `:analyzers` promotion by digest retag | `promote` job (no rebuild) |
| Cosign keyless signatures on both digests | `sign-attest` job |
| SLSA build-provenance attestations | `actions/attest-build-provenance` steps |
| SPDX SBOM + SBOM attestations | `sbom-scan` + `actions/attest-sbom` |
| Python sdist/wheel artifact | `build-dist` → `artifact-python-dist` |

Verify a published digest locally (see [CONTRIBUTING.md](../CONTRIBUTING.md#verify-a-published-image)).

## Operator actions (D17)

### PyPI (`merge-craft`)

PyPI distribution name is **`merge-craft`** (hyphen); import and CLI remain
`mergecraft`. Craft publishes via the `pypi` target in [`.craft.yml`](../.craft.yml).

**Prerequisites**

1. Repository secrets: `TWINE_USERNAME`, `TWINE_PASSWORD` (API token as password).
2. `GITHUB_TOKEN` with `repo` for `craft prepare` / `craft publish`.
3. Release preconditions green on the release branch (live integration, E2E nightly,
   image SBOM + Trivy gate) — see [CONTRIBUTING.md](../CONTRIBUTING.md#releases-craft).

**Cut and publish 0.1.0**

```bash
craft prepare 0.1.0          # first release — explicit version, not `auto`
# Wait for CI/CD on the release branch (build, scan, sign, attest, promote).
craft publish 0.1.0          # uploads dist/* to PyPI + GitHub release per .craft.yml
```

Or dispatch **Release** (`.github/workflows/release.yml`) with `version: 0.1.0`,
then `craft publish 0.1.0` after CI is green.

Post-publish smoke:

```bash
pip install merge-craft==0.1.0
mergecraft --help
```

### GitHub Marketplace listing

> **SCM scope:** mergeCraft 0.1.0 supports **GitHub** repositories only. GitLab support
> is planned via the `ScmProvider` abstraction and will be documented when available.

Marketplace is **not** automated by Craft. After the public GitHub release and
Docker `:latest` promotion:

> **Prerequisite — verify image attestations before listing.**
> Run the `cosign verify` and `gh attestation verify` commands in
> [CONTRIBUTING.md § Verify a published image](../CONTRIBUTING.md#verify-a-published-image)
> against the release-tag digest. The signatures and attestations are produced by
> the `sign-attest` job in `.github/workflows/ci-cd.yml`. Do **not** submit the
> Marketplace listing until both verifications pass for the release tag.

1. Open [GitHub Marketplace new action](https://github.com/marketplace/actions/new).
2. Point at `alexhawat/mergeCraft` and the release tag (`v0.1.0`).
3. Use the Docker action entry (`action.yml` + `ghcr.io/alexhawat/mergecraft` image).
4. Categories: **Code review**, **Continuous integration**.
5. Link docs: `docs/`, `REVIEW-CHECKS.md`, `docs/ANALYZERS.md`.
6. Note BYOK / no SaaS backend in the listing description (see README positioning).
7. Note GitHub-only SCM scope for 0.1.0 in the listing description.

### README assets

The mark and wordmark are already tracked in [`assets/brand/`](../assets/brand/) — nothing
to add there. The one binary still outstanding is the demo capture; see
[`docs/assets/README.md`](assets/README.md) for what's needed and where it goes.

## Python version and Docker (D16)

**Python >=3.11** is the install floor for `uv tool install` / local CLI development
(`pyproject.toml`). CI runs on **3.11** and **3.14**. PyPI (`merge-craft`) is **not**
published yet — install from git or a local checkout via `uv`. Operators who want a
pinned runtime without managing Python versions should use the **Docker Action**
(`alexhawat/mergeCraft@…`) — the image ships a compatible runtime; no local Python
install is required.

## Shipped package names (D15)

| Path | Status |
|------|--------|
| `src/mergecraft/yes/` | **Live** — async retry primitive (`mergecraft.yes.op`) used by `mergecraft watch`. Name is intentional; not renamed in this release (API surface). |

## Prototype residue removed for 0.1.0

- `docs/meat-spike.md` — spike write-up (issue #60 exploration).
- `meat_python_plus/` — experimental Python port of [meat](https://github.com/boldsoftware/meat);
  not imported by shipped `mergecraft`. Optional Meat reading-diff lens uses the
  `meat` Go binary (`go install meat.dev/cmd/meat@latest`) via `meat_harness`.

## MCP Registry (`server.json`)

Repo-root [`server.json`](../server.json) is **generated** by
`scripts/gen_mcp_server_json.py` from the public MCP tool catalog and
`pyproject.toml` version. Regenerate with `make mcp-server-json`; CI runs
`make mcp-server-json-check` (schema validation against a vendored snapshot plus
`--check` drift gate). The artifact advertises the **public** six-tool stdio
profile (`mergecraft mcp serve --role public --transport stdio`) and PyPI
package `merge-craft` — not the runtime reviewer/verifier harness bag.

**Live registry publish is operator-owned (G3):** after a tagged release, run
`mcp-publisher` against the generated `server.json` under namespace
`io.github.alexhawat/mergecraft`. PR CI does not publish to the MCP Registry.
