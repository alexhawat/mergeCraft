# Local repo-native analyzers

mergeCraft's analyzer catalog includes several `runtime: repo-native` tools that
must be present in the checkout (`.venv/bin`, `node_modules/.bin`, or a
first-level `*/node_modules/.bin`) before `mergecraft review --shell enabled`
can run them offline.

## Installed by `make setup`

| Analyzer | Catalog version | Install path |
| --- | --- | --- |
| `vulture` | `2.14` | `pyproject.toml` `[project.optional-dependencies] dev` → `.venv/bin` |
| `typos` | `1.32.0` | same dev extra → `.venv/bin` |
| `markdownlint-cli` | `0.44.0` (npm) | `tools/package.json` → `tools/node_modules/.bin` |
| `markdownlint` (engine) | `0.37.4` | resolved via `tools/package-lock.json` (catalog `version:`) |
| `jscpd` | `4.1.0` | same npm tooling package |

Pins match the `version:` fields in `src/mergecraft/analyzers/catalog/*.yaml` and
are locked via `uv.lock` (Python) and `tools/package-lock.json` (npm). `make setup`
runs `uv sync --extra dev` and a **soft** npm install via `make setup-local-analyzers`:
when `npm` is missing or `npm ci` fails, setup prints a warning and continues —
`markdownlint` and `jscpd` are skipped locally until `tools/node_modules` exists.
`make npm-lockcheck` (in `make lint`) still enforces lockfile drift when npm is on PATH.

## Intentionally skipped in this repo

| Analyzer | Catalog version | Why skipped |
| --- | --- | --- |
| `knip` | `5.42.0` | Vendor JavaScript under `docker/agent-clis/` — not first-party code; `knip` would flag unused exports in vendored agent CLI trees. |
| `tsc` | `5.8.3` | No first-party `tsconfig.json` in this repository. Installing `tsc` would typecheck vendored sources under `docker/agent-clis/`, which is noise for mergeCraft dogfood reviews. |

Consumer repositories that own a `package.json` / `tsconfig.json` can install
these tools locally; mergeCraft still skips them with the standard
`not found in repo PATH or tooling` reason when the binary is absent.

Do **not** flip these manifests to `runtime: managed` or add darwin provenance —
they stay `runtime: repo-native` per catalog policy (C3/D5).
