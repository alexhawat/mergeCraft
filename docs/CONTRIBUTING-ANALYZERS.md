# Contributing analyzers

Add a new catalog tool with **one manifest YAML**, **one parser fixture**, and **one
`docs/ANALYZERS.md` row**. mergeCraft runs the platform — not bespoke Python per tool (D16/C6).

## Checklist

1. Add `src/mergecraft/analyzers/catalog/<id>.yaml` (see fields below).
2. Add a parser fixture under `tests/analyzers/fixtures/`:
   - SARIF tools → `sarif/<id>-minimal.sarif.json`
   - Native JSON/JSONL → `native/<id>-minimal.json` or `.jsonl`
3. Regenerate docs: `uv run python -m mergecraft.analyzers.catalog_docs`
4. Confirm `make catalog-check` passes.
5. Open a PR — CI fails when fixture, doc row, or `severity_map` is missing (C5).

## Manifest fields

| Field | Purpose |
|-------|---------|
| `id` | Stable catalog id (kebab-case). |
| `category` | Review taxonomy bucket (`lint`, `security`, `vuln`, `contract`, …). |
| `languages` | Tags for docs; may be empty. |
| `detect.files` | Globs; analyzer considered when a changed path matches. |
| `command` | argv template; `{files}` expands to scoped changed paths. |
| `scope` | `diff` or `repo`. |
| `parser` | Existing parser id (`sarif`, `ruff_json`, …) or `*_native` for inline adapters. |
| `severity_map` | Maps **every** native severity the parser emits → review taxonomy. |
| `default_enabled` | `false` for P1–P3 long tail; `auto` only with strong repo detection. |
| `runtime` | `repo-native` → `managed` → `container` (D4). |
| `trust` | `trusted` or `untrusted` (D7). |
| `exclusive_group` | One winner per group unless repo overrides both (D13/C1). |
| `declared_unavailable` | Honest skip reason when the tool cannot run yet (C6.4). |

## Choosing a parser

Prefer an existing parser in `src/mergecraft/analyzers/parsers/`. Most linters expose
SARIF — use `parser: sarif` and map `error` / `warning` / `note`.

If the tool needs custom parsing (like `buf breaking` or `agentsec`), use a `*_native`
parser id and register native severities in `manifest._PARSER_NATIVE_SEVERITIES`. **Do not
add bespoke adapter Python for a standard linter output** — that is a W2 platform defect.

## Severity map

Every key the parser can emit must appear in `severity_map`. Values must be review taxonomy
severities (`Critical`, `Major`, `Minor`, `Trivial`). CI calls `severity_map_complete()`.

## Trust and provenance

- Managed binaries: pin `version`, `provenance[platform].url`, and `sha256`.
- Untrusted fork PRs: no secret verification, no network unless allowlisted (D7/C2).
- Container-only heavy tools: `runtime: container`, `default_enabled: false` (D18/C4).

## Exception list (bespoke Python allowed)

| Entry | Justification |
|-------|----------------|
| `oasdiff_json`, `squawk_json` parsers (C4.5) | Differential contract output shapes — only new parsers in the catalog plan. |
| `agentsec/*` manifest readers (C5) | MCP/skill manifests are inputs, not linter stdout; rules stay YAML (C7). |
| `catalog_docs.py`, `cli/analyzers_cmd.py` (C6) | Contributor path and enforced catalog documentation. |
| `declared_unavailable` + `resolve_analyzer` skip (C6.4) | Honest skip for compile-db and non-Linux tools without fake runs. |

## Declared-but-not-runnable (C6.4)

These ship as manifests so repos can opt in later, but always skip with `declared_unavailable`:

| id | Reason |
|----|--------|
| `clang-tidy` | Requires `compile_commands.json` — mergeCraft never guesses compiler flags. |
| `infer` | Requires compilation database and container build. |
| `psscriptanalyzer` | Windows/macOS runner — Linux out of scope. |
| `blinter` | Windows batch — Linux runner out of scope. |
| `swiftlint` | macOS toolchain — Linux runner out of scope. |
| `languagetool` | Manifest-only — runtime not bundled (C6 out of scope). |
| `shopify-theme-check` | Manifest-only — runtime not bundled. |
| `smarty-lint` | Manifest-only — runtime not bundled. |
| `fortitude` | Manifest-only — runtime not bundled. |

**Deferred:** ShellCheck on workflow `run:` blocks (parent W6.3) — inline shell in YAML
 lacks reliable line mapping to workflow file lines; revisit when mapping is clean.

## P3 example

Adding `luacheck` is representative of the long tail:

1. Copy a similar manifest (e.g. `rubocop.yaml`).
2. Adjust `detect.files`, `command`, and `languages`.
3. Add `tests/analyzers/fixtures/sarif/luacheck-minimal.sarif.json`.
4. Run `mergecraft analyzers explain luacheck` and `make catalog-check`.

No Python changes required.
