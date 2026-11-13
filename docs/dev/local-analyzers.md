# Local repo-native analyzers

mergeCraft's analyzer catalog includes several `runtime: repo-native` tools that
must be present in the checkout (`.venv/bin`, `node_modules/.bin`, or a
first-level `*/node_modules/.bin`) before `mergecraft review --shell enabled`
can run them offline.

## Installed by `make setup`

| Analyzer | Catalog version | Install path |
| --- | --- | --- |
| `vulture` | `2.16` | `pyproject.toml` `[project.optional-dependencies] dev` → `.venv/bin` |
| `typos` | `1.52.0` | same dev extra → `.venv/bin` |
| `markdownlint-cli` | `0.50.0` (npm) | `scripts/package.json` → `scripts/node_modules/.bin` |
| `markdownlint` (engine) | `0.42.1` | resolved via `scripts/package-lock.json` (catalog `version:`) |
| `jscpd` | `4.1.0` | same npm tooling package |

Pins match the `version:` fields in `src/mergecraft/analyzers/catalog/*.yaml` and
are locked via `uv.lock` (Python) and `scripts/package-lock.json` (npm). `make setup`
runs `uv sync --extra dev` and a **soft** npm install via `make setup-local-analyzers`:
when `npm` is missing or `npm ci` fails, setup prints a warning and continues —
`markdownlint` and `jscpd` are skipped locally until `scripts/node_modules` exists.
`make npm-lockcheck` (in `make lint`) still enforces lockfile drift when npm is on PATH.

`markdownlint-cli` 0.50.0 requires **Node >= 22** (0.45.0 dropped Node 18, 0.49.0
dropped Node 20, and a transitive dependency wants >= 22.12.0). `docker/Dockerfile`,
`docker/Dockerfile.analyzers` and `integration.yml` all pin Node 22, so CI and the
shipped image are fine. Locally, `make setup-local-analyzers` fails soft: on
Node 20 the install prints `EBADENGINE`, appears to succeed, and `markdownlint`
and `jscpd` then silently stop working. Check `node --version` if either goes
quiet.

The engine bump also enables `MD060` (`table-column-style`) by default, which
fires on this repo's docs tables. Repo-root `.markdownlint.json` disables it —
see the note in that file. Consumers with no markdownlint config receive the
same MD060-only disable via the shipped `markdownlint-default-config.json`
fallback; a run note records that the fallback applied so operators can tell
repo-rules-clean from fallback-clean. A consumer whose own config enables
MD060 still gets it.

## Intentionally skipped in this repo

| Analyzer | Catalog version | Why skipped |
| --- | --- | --- |
| `knip` | `5.42.0` | Vendor JavaScript under `docker/agent-clis/` — not first-party code; `knip` would flag unused exports in vendored agent CLI trees. |
| `tsc` | `5.8.3` | No first-party `tsconfig.json` in this repository. Installing `tsc` would typecheck vendored sources under `docker/agent-clis/`, which is noise for mergeCraft dogfood reviews. |

Consumer repositories that own a `package.json` / `tsconfig.json` can install
these tools locally; mergeCraft still skips them with the standard
`not found in repo PATH or tooling` reason when the binary is absent.

Do **not** flip these manifests to `runtime: managed` or add darwin provenance —
they stay `runtime: repo-native` per catalog policy.

## Analyzer latency and managed caches

The catalog pipeline runs up to four independent adapters concurrently. Trust,
shell and analyzer-mode checks happen before scheduling; results retain catalog
order. Contract adapters reuse their provisioned binary across changed files,
while each invocation still goes through configuration and sandbox checks.

Managed downloads are already reused across CLI runs under
`$XDG_CACHE_HOME/mergecraft/analyzer-cache` (or
`~/.cache/mergecraft/analyzer-cache`). The cache is keyed by tool, platform and
pinned artifact digest; cached binaries are checked against their pin-bound
receipts before reuse. Keep this directory outside the reviewed checkout: a
cache inside the checkout is refused. The checkout's
`.mergecraft/analyzers.lock` records resolutions; it is not a trusted cache.

Docker Action jobs have fresh filesystems, so the default `auto` mode may
provision again on each job. For latency-sensitive deployments, use the baked
analyzer image built from `docker/Dockerfile.analyzers`; it sets
`MERGECRAFT_ANALYZERS=full`. Selecting `full` alone does not install tools into
the slim image. See [distribution](../distribution.md) for image tags.

If an operator persists the managed cache across jobs, mount it outside the
checkout and key the restore by platform and the trusted catalog's provenance
digests. Save only from trusted jobs; untrusted and fork jobs must be restore-only
and must never update a cache consumed by trusted jobs. The Action does not
configure an Actions cache automatically.
