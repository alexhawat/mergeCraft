# Test plan — a prepared release branch keeps `server.json` in step with the package version

**Owner:** `test-creator` · **Branch:** `wave/release-candidate` · **Base:** `origin/main` @ `ca8bba15`
**Trace run:** service `mergecraft-dev` · wave.plan=release-candidate · run.id=`bbd271be-7ea1-4011-b733-bf9201fea9c2` · wave.id=`RC2`
**Test module:** `tests/release/test_prepare_version_bump.py` — 14 collected nodes.
Row 3 of the map below is the shared setup guard those nodes depend on, not a node of its own.

**Status: RED by design.** `scripts/bump-version.sh` does not exist and `.craft.yml`
names no `preReleaseCommand`, so all 14 pins fail. The suite collects with no
errors, `make lint` and `make typecheck` exit 0, and `tests/mcp/test_server_json.py`
stays green (7 passed). The implementation wave makes these real passes; the pins
carry no `xfail` marker, because `xfail_strict = true` in `pyproject.toml` would
turn a later pass into a failure.

## The contract this suite pins

A `craft prepare` run must leave the prepared branch self-consistent:

| Source | Contract |
| --- | --- |
| Decision RC-D4 | `.craft.yml` gains `preReleaseCommand: bash scripts/bump-version.sh`. Defining the command switches off Craft's automatic `pyproject.toml` bump, so the script does the bump itself: `[project].version` **and** both `server.json` version fields (`version`, `packages[0].version`). |
| Decision RC-D4 | The script's `server.json` output is **byte-identical** to `scripts/gen_mcp_server_json.render_server_json()` rendered for the new version. `make mcp-server-json-check` is not weakened. |
| Decision RC-D4 | `python3` (stdlib) plus `perl` only — no project import and no `.venv`, because the Release workflow's `prepare` job runs it with no bootstrap. |
| Recorded dry run (craft 2.28.0 `runCustomPreReleaseCommand`) | Craft invokes the command **positionally**: `bash scripts/bump-version.sh <oldVersion> <newVersion>`, passing `0.0.0` for an empty old version, and additionally exports `CRAFT_NEW_VERSION` / `CRAFT_OLD_VERSION`. |
| Trace finding K3 | The failure this closes: Craft's auto-bump edited `pyproject.toml` alone, the committed `server.json` went stale, and the prepared branch failed `make mcp-server-json-check` (`drift server.json`) before reaching any target. |

## Contract → test map

| # | Contract | Node id | Layer | Class |
| --- | --- | --- | --- | --- |
| 1 | `.craft.yml` names the prepare command and keeps the post-release one | `test_craft_yml_names_the_prepare_and_post_release_commands` | unit (config) | happy |
| 2 | One run sets `[project].version`, `server.json.version`, `packages[0].version` | `test_prepare_bump_sets_pyproject_and_both_server_json_versions` | functional (shell E2E) | happy |
| 3 | The named script exists and runs in a throwaway repo root with `scripts/` beside the files it edits | shared setup for nodes 2, 4–13 (`_prepare_tree`) | integration | premise guard |
| 4 | Runs with `VIRTUAL_ENV` unset and no project environment on `PATH` | `test_prepare_bump_runs_without_the_project_environment` | functional (workflow shape) | happy |
| 5 | Positional invocation, no `CRAFT_*` environment required | `test_prepare_bump_reads_positional_old_and_new_arguments[old-version-from-branch]` | integration | happy |
| 6 | Craft's empty old version arrives as `0.0.0` | `test_prepare_bump_reads_positional_old_and_new_arguments[empty-old-version-is-0.0.0]` | integration | edge |
| 7 | Craft's exported `CRAFT_NEW_VERSION` / `CRAFT_OLD_VERSION` do not break the run | `test_prepare_bump_tolerates_craft_version_env_exports` | integration | edge |
| 8 | Output is byte-identical to the generator render for the new version | `test_server_json_after_bump_is_byte_identical_to_the_generator_render` | integration (script ↔ generator) | happy |
| 9 | Only `pyproject.toml` and `server.json` change: no `uv.lock`, no `CHANGELOG.md`, no `docs/mcp-tools.md` | `test_prepare_bump_touches_only_pyproject_and_server_json` | integration | edge |
| 10 | Non-ASCII survives unescaped (`ensure_ascii` stays off, as in the generator) | `test_prepare_bump_preserves_non_ascii_without_escaping` | unit (serialization) | edge |
| 11 | No arguments: exit non-zero, both files untouched | `test_prepare_bump_refuses_a_missing_or_empty_new_version[no-arguments]` | functional | error |
| 12 | Empty new version: exit non-zero, both files untouched | `test_prepare_bump_refuses_a_missing_or_empty_new_version[empty-new-version]` | functional | error |
| 13 | `server.json` missing its top-level `version`: fail loudly, not silently repaired | `test_prepare_bump_fails_loudly_when_server_json_drops_a_version_field[top-level-version]` | integration | error |
| 14 | `server.json` missing `packages[0].version`: fail loudly, not silently repaired | `test_prepare_bump_fails_loudly_when_server_json_drops_a_version_field[package-version]` | integration | error |
| 15 | Script shape: SPDX header, `set -euo pipefail`, script-relative root, no `uv`, no project import | `test_bump_script_stays_bootstrap_free` | unit (source shape) | edge |

Coverage across the three scenario classes: happy (1, 2, 4, 5, 8), edge (6, 7, 9, 10, 15),
error (11, 12, 13, 14). Every node fails today on the missing script or the
missing configuration key, and none fails for a fixture, import, or collection
reason: the shape of the RED result is 14 `failed`, 0 `error`.

## Why the strong pins are strong

- **Byte identity (8)** is the property whose absence produced the failed
  candidate. The test loads `scripts/gen_mcp_server_json.py` by path, checks
  first that its unpatched render already equals the committed `server.json`
  (so a wrong expectation cannot pass vacuously), then patches
  `scripts.gen_mcp_server_json.package_version` to the new version and compares
  the script's rewritten file byte for byte.
- **Only two files change (9)** is a whole-tree byte snapshot of the throwaway
  root, with `uv.lock`, `CHANGELOG.md` and `docs/mcp-tools.md` copied in so the
  assertion has something to protect: a bump that ran `uv lock` or regenerated
  through the full generator would change them. The changed set must be exactly
  `["pyproject.toml", "server.json"]`.
- **Positional contract (5, 6)** runs with `CRAFT_NEW_VERSION`/`CRAFT_OLD_VERSION`
  removed from the environment, so an implementation that only reads the
  environment (the shape `scripts/post-release.sh` uses) cannot pass. Node 7 pins
  the tolerant direction: Craft also exports them, and the run must still work.
- **No bootstrap (4, 15)**: node 4 runs the script with `VIRTUAL_ENV` removed and
  every `.venv*` entry stripped from `PATH`, and asserts that premise before
  asserting the outcome; node 15 pins that the script shells out to neither `uv`
  nor an import of `mergecraft`.
- **Error cases (11–14)** assert both the non-zero exit and the untouched files,
  because a half-bumped release branch carries a version nobody chose. The
  missing-field cases (13, 14) use assignment-free mutation of the copied
  manifest, so a script that reassigns `data["version"]` without checking is
  caught rather than silently creating the key.

## Reproduction

```bash
cd /Users/alex/Documents/code/sevn.bot/mc-release
UV_PROJECT_ENVIRONMENT="$PWD/.venv-dev" uv run pytest tests/release -q --collect-only   # 29 collected, no errors
UV_PROJECT_ENVIRONMENT="$PWD/.venv-dev" uv run pytest tests/release -q                 # 14 failed, 15 passed  (the RED wave)
UV_PROJECT_ENVIRONMENT="$PWD/.venv-dev" uv run pytest tests/mcp/test_server_json.py -q  # 7 passed
UV_PROJECT_ENVIRONMENT="$PWD/.venv-dev" make lint && make typecheck                     # both exit 0
```

No test touches the network, and no test needs a live gate: the whole contract is
local file state plus one subprocess invocation of the prepare command.

## Ambiguities resolved while authoring

| Ambiguity | Resolution |
| --- | --- |
| Mark the pins `xfail(strict=False)`, or let them fail? | They fail, marker-free. `pyproject.toml` sets `xfail_strict = true`, and the wave plan expects each pin red so the very next wave greens it in the same PR; a marker would have to be removed again and would risk a strict-XPASS failure. Several existing RED suites in this repository record the same choice. |
| Does the script need `CRAFT_NEW_VERSION` when the positional form is present? | No. The brief for this wave says the implementation is written against the positional contract, so the pins prove the positional form suffices (nodes 5, 6) and tolerate the environment exports Craft also sets (node 7). No test asserts precedence between the two sources: Craft always passes them consistently, so precedence is not observable behaviour. |
| How is "no other file changes" checked inside `tmp_path` (no git repo)? | A byte snapshot of the whole copied tree, not `git status`, with the three watched siblings copied in as real inputs. |
| Which spellings of the script-relative root are accepted? | `dirname` plus either `$0` or `BASH_SOURCE`, so the stricter `BASH_SOURCE[0]` form is allowed; what is pinned is that the root comes from the script's own location, which is what makes the throwaway-root tests meaningful. |
| Is the `postReleaseCommand` check part of this wave? | It rides with the configuration pin (node 1): adding `preReleaseCommand` must not disturb the publish-time hook that is already there. |
