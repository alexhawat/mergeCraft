# Test plan — open GitHub issues sweep (2026-08-19)

**Plan:** `.ignorelocal/waves/open-issues-sweep-2026-08-19-wave-plan.md`
**Branch:** `wave/open-issues-sweep-2026-08-19` (single worktree, waves serial)
**Owner:** `test-creator` — the only agent that may edit `tests/`.

## How to use this document

The program has **six RED waves**, one per logical batch. Each RED wave appends **its own
`## Batch <X>` section** below and touches nothing else in this file:

| Batch | RED wave | Section | Status |
|---|---|---|---|
| A — MCP security (#257, #258, #260, #259) | W1 | [Batch A](#batch-a--mcp-security-w1) | **reconciled — all green** |
| B — Action / workflow contract (#264, #265, #272, #271) | W6 | [Batch B](#batch-b--action--workflow-contract-w6) | **authored — 17 RED (W7/W8/W9)** |
| C — Analyzer correctness (#270, #269, #268) | W10 | _append below_ | pending |
| D — Agents + approve gate (#222, #261, #262, #273, #263) | W14 | _append below_ | pending |
| E — MCP contract (#266, #267) | W20 | _append below_ | pending |
| F — Auth DX + #220 close (#221, #220) | W23 | _append below_ | pending |

Section template each batch follows: **Contract → test map** table, **Confirmed-RED assertions**
list, **Green-today regression guards** list, **Inverted assertions** (if any), and
**Escalation log** (appended only when an implementation wave exhausts its attempts and the test —
not the code — turns out to be wrong).

Conventions for every batch:

- Cross-wave reds use `@pytest.mark.xfail(reason="green after W<N>: …", strict=False)`. Never
  `strict=True` — a strict xfail that starts passing becomes `XPASS(strict)` and breaks the suite
  the implementation wave was forbidden from touching.
- Each implementation wave removes only the xfail markers tagged with its own wave number.
- Verification per RED wave: `make lint`, `make typecheck`, and a clean
  `uv run pytest --collect-only -q` on the touched paths. Assertions stay red.

---

## Batch A — MCP security (W1)

**Authored:** 2026-08-19 (`1b1cb3e`) · **Greened by:** W2 `f8ad50f` (#257), W3 `605d3a5` (#258),
W4 `c81c545` (#260), W5 `f1378f7` (#259) · **Markers reconciled:** 2026-08-19 —
all 15 `xfail` decorators (27 parametrized instances) removed; the three files are
**47 passed, 0 xfail, 0 xpass**.
**Files:** `tests/mcp/test_git_tool.py` (extended), `tests/mcp/test_upload.py` (new),
`tests/mcp/test_labels.py` (new)

### Contract → test map

| Issue | Contract (source) | Layer | Test | Greened by |
|---|---|---|---|---|
| #257 / D7 | Read-only subcommand allowlist — `reset`, `clean`, `stash`, `update-ref` rejected (`mcp/git.py:20` `_SUBCOMMAND_RE` is format-only) | unit | `test_mutating_subcommands_rejected[reset|clean|stash|update-ref]` | W2 |
| #257 / D7 | `branch` is read-only: `-D` / `-d` / `-m` rejected | unit | `test_branch_mutation_flags_rejected[-D|-d|-m]` | W2 |
| #257 / D7 | Allowlist keeps every read-only subcommand callable | unit | `test_readonly_subcommands_allowed[…11 cases]` | green today |
| #257 | `git -c alias.x='!true' status` rejected regardless of `payload.shell` (command string form) | unit | `test_dash_c_alias_rejected_regardless_of_shell[disabled|restricted|enabled]` | W2 |
| #257 | Same via `args` (`["-c", "alias.x=!true"]`) | unit | `test_dash_c_alias_in_args_rejected_regardless_of_shell[…]` | W2 |
| #257 / D7 | `-c` / `--config-env` never forwarded, even benign (`core.quotepath=false`) | unit | `test_c_config_option_rejected[flag_args0|flag_args1]` | W2 |
| #257 / D7 | `-C` outside the primary repo root rejected | unit | `test_global_c_option_outside_repo_root_rejected` | W2 |
| #257 / D7 | `-C` inside the primary repo root still forwarded before the subcommand | unit | `test_global_c_option_inside_repo_root_is_forwarded` | green today |
| #257 / D7 | `--work-tree` outside the repo root rejected | unit | `test_work_tree_outside_repo_root_rejected` | W2 |
| #257 / D7 | `--git-dir=…` outside the repo root rejected | unit | `test_git_dir_outside_repo_root_rejected` | W2 |
| #257 / D7 | Confinement also applies when the option arrives inside the `command` string | integration | `test_global_opt_in_command_string_outside_repo_root_rejected` | W2 |
| #258 / D8 | Path outside repo root **and** `ctx.tmpdir` rejected; no `file://` URI returned | integration | `test_path_outside_repo_and_tmpdir_rejected` | W3 |
| #258 / D8 | Symlink rejected (tmp stand-in target, not a real `/etc/passwd` read) | integration | `test_symlink_escape_rejected` | W3 |
| #258 / D8 | Relative `..` traversal out of the repo root rejected | integration | `test_relative_traversal_out_of_repo_rejected` | W3 |
| #258 / D8 | In-repo file still uploads in BYOK mode (`file://` under `tmpdir/uploads`) | functional | `test_in_repo_file_still_uploads_in_byok_mode` | green today |
| #258 / D8 | File under `ctx.tmpdir` still uploads | functional | `test_tmpdir_file_still_uploads_in_byok_mode` | green today |
| #260 | `remove_labels` percent-encodes the label segment of the delete URL (`/`, space, `..`) | integration | `test_label_name_is_percent_encoded_in_delete_url[area/mcp|needs info|../evil]` | W4 |
| #260 | Plain label leaves the delete URL byte-identical | integration | `test_plain_label_delete_url_is_unchanged` | green today |
| #259 / D9 | Every `commit_changes` return carries `pushed: bool`; no Git Data ref `PATCH` | integration | `test_commit_changes_always_reports_pushed_and_never_patches_ref` | W5 |
| #259 / D9 | Tool description no longer claims a GitHub-signed commit | unit | `test_commit_changes_description_does_not_claim_signed` | W5 |
| #259 | Push-policy-skip path already reports `pushed: False` | integration | `test_commit_changes_push_policy_skip_reports_pushed_false` | green today |

### Reconciled assertions (were 27 xfailed → now 27 real passes)

Every marker was xpassing before the strip, so the reconciliation removed markers only — no
assertion was weakened and none needed escalation.

- **#257 → W2 (19):** four mutating subcommands, three `branch` flags, six `-c`-alias cases
  (3 shells × command-string and args forms), two `-c`/`--config-env` forwarding inversions,
  and four path-confinement cases (`-C` args, `-C` command string, `--work-tree`, `--git-dir`).
- **#258 → W3 (3):** outside-root path, symlink escape, relative traversal.
- **#260 → W4 (3):** `area/mcp`, `needs info`, `../evil`.
- **#259 → W5 (2):** `pushed` key + no ref `PATCH`; description wording.

Docstring narration that described the pre-fix defect in the present tense
(`test_c_config_option_rejected`, `test_dash_c_alias_rejected_regardless_of_shell`, the
`test_labels.py` module docstring) was rewritten to state the contract instead.

### Green-today regression guards (20 passed)

The five pre-existing normalization tests, the eleven read-only allowlist cases, in-root `-C`
forwarding, both BYOK upload success paths, the plain-label delete URL, and the push-policy-skip
`pushed: False` path. These must stay green through W2–W5.

### Inverted assertions

Four assertions in `tests/mcp/test_git_tool.py` asserted the **vulnerable** behaviour and were
inverted rather than left green:

| Was | Now | Why the old assertion was wrong |
|---|---|---|
| `test_global_c_option_is_forwarded` — `-C /some/repo/dir` forwarded | `test_global_c_option_outside_repo_root_rejected` (+ in-root positive case) | Pinned unconfined `-C`: a reviewer-surface tool could be pointed at any directory on the runner. D7 confines it to the primary repo root. |
| `test_c_config_option_forwarded` — `-c core.quotepath=false` forwarded | `test_c_config_option_rejected` | D7 drops `-c` / `--config-env` from `_extract_global_opts` **unconditionally**. There is no safe `-c`: allowing benign keys means the extraction path that makes `-c alias.x='!cmd'` reachable stays alive. This inversion is beyond the plan's literal "invert `:110-115`" note but is required by D7 — flagged for W2. |
| `test_git_dir_global_option_forwarded` — `--work-tree /some/repo/dir` forwarded | `test_work_tree_outside_repo_root_rejected` | Same unconfined-path defect as `-C`. |
| `test_global_opt_in_command_string_forwarded` — `git -C /some/repo/dir status` forwarded | `test_global_opt_in_command_string_outside_repo_root_rejected` | Confinement must not depend on whether the option arrived in `command` or `args`. |

### Post-reconciliation contract audit

Both mid-batch judgement calls were re-checked against the RED contract:

- **W2 read D7 literally and rejected `-c` outright**, including the benign
  `-c core.quotepath=false` case W1 had inverted. That matches the inverted assertion recorded
  above — `test_c_config_option_rejected[flag_args0]` was authored expecting exactly this, so
  no assertion had to move. `_confine_to_repo_root` is still exercised through the in-root
  positive case (`test_global_c_option_inside_repo_root_is_forwarded`), so the allowlist cannot
  be tightened into a blanket refusal without a red test.
- **W3's local `_check_upload_path()` duplicates path confinement** with `mcp/git.py`'s
  `_confine_to_repo_root()`, both using `resolved.startswith(root + os.sep)` rather than
  `Path.is_relative_to`. **No test in this batch names either helper or asserts the matching
  strategy** — every assertion goes through the public tool surface (`upload_file_tool`,
  `git_tool`) and checks only `is_error` plus the message contract. A later refactor that unifies
  the two helpers, or swaps string-prefix matching for `Path.is_relative_to`, keeps all 47 tests
  green as long as the behaviour holds.
- `test_symlink_escape_rejected` uses a symlink whose target escapes the repo root, so it does
  **not** over-fit to W3's blanket "any symlink is refused" rule: a resolve-then-confine
  implementation rejects the same fixture. Nothing pins the in-repo-symlink case either way.

### Notes for W2–W5 implementers (historical)

- **Error-message contract:** the three `-C` / `--work-tree` / command-string confinement tests
  assert the offending path appears in the error text. Keep the rejected value in the message.
- **`--git-dir`** is asserted only as "rejected" (no message contract) because the inline
  `--flag=value` form makes the echoed value ambiguous.
- **`commit_changes`** tests patch `mergecraft.mcp.git._run_git` with a recorder that serves the
  real argv sequence (`rev-parse --abbrev-ref HEAD`, `status --porcelain`, `add -A`, `commit`,
  `rev-parse HEAD`) and bind a `GitHubClient` subclass that records `patch()` calls. W5 must leave
  the local-commit argv intact; only the ref `PATCH` and the `pushed` key change.
- **Upload fixtures** build every path in sync fixtures (`repo_root`, `scratch`, `outside_file`,
  `symlink_into_outside`, `traversal_path`) because `tests/**` is not exempt from ruff `ASYNC240`
  — do not move `pathlib` calls into the async test bodies.

### W5b — path-confinement hardening guards (orchestrator-inserted)

Inserted after AF from a residual-risk report claiming both confinement helpers tested
containment with a **bare string prefix**, which a sibling directory like `<root>-evil` would
defeat. **Reading the source settles it — the claim is wrong.** Both helpers already anchor on a
separator and both accept the exact root:

| Helper | Containment expression |
|---|---|
| `_confine_to_repo_root` (`src/mergecraft/mcp/git.py`) | `resolved == resolved_root or resolved.startswith(resolved_root + os.sep)` |
| `_check_upload_path` (`src/mergecraft/mcp/upload.py`) | `any(resolved == r or resolved.startswith(r + os.sep) for r in allowed)` |

The 11 guards below are therefore **plain green regression tests — none are RED, none carry an
xfail marker.** They exist to keep the `+ os.sep` anchor (or any successor) from regressing.

| Contract | Coverage | Layer / class |
|---|---|---|
| Sibling `<root>-evil` rejected on every git path option | `tests/mcp/test_git_tool.py::test_sibling_prefix_directory_rejected` (5 params: `-C`, `--git-dir` both forms, `--work-tree` both forms) | Functional, error |
| Prefix match with no separator (`<root>evil`) rejected | `tests/mcp/test_git_tool.py::test_sibling_prefix_without_separator_rejected` | Functional, edge |
| Repo root itself still accepted (bare, trailing `/`, trailing `/.`) | `tests/mcp/test_git_tool.py::test_repo_root_itself_still_accepted` (3 params) | Functional, happy/edge |
| Nested in-root path still forwarded | `tests/mcp/test_git_tool.py::test_nested_path_inside_repo_root_still_accepted` | Functional, happy |
| Sibling rejected on **both** upload arms (repo root *and* tmpdir) | `tests/mcp/test_upload.py::test_sibling_prefix_directory_rejected` (2 params) | Functional, error |
| Upload prefix match with no separator rejected | `tests/mcp/test_upload.py::test_sibling_prefix_without_separator_rejected` | Functional, edge |
| Deeply nested in-repo upload still succeeds | `tests/mcp/test_upload.py::test_deeply_nested_in_repo_file_still_uploads` | Functional, happy |
| Redundant `/./` segment inside the root still succeeds | `tests/mcp/test_upload.py::test_in_repo_file_reached_via_trailing_separator_still_uploads` | Functional, edge |

Refactor-survival: as with Batch A, no assertion names `_confine_to_repo_root`,
`_check_upload_path`, `startswith`, or `Path.is_relative_to`. Every guard drives the public tool
surface and asserts only `is_error`, the recorded git argv, and — where the existing W2 contract
already requires it — that the offending path appears in the rejection text. Unifying the two
helpers or swapping to `Path.is_relative_to` keeps all 11 green.

Fixtures create the sibling directories **on disk** (`tmp_path/repo` next to `tmp_path/repo-evil`)
rather than hand-crafting strings, so `Path.resolve()` cannot collapse the distinction and the
test genuinely exercises containment rather than normalization.

### Escalation log

_(empty)_

---

## Batch B — Action / workflow contract (W6)

**Issues:** `#264` (wait-for-ci cannot read check-runs), `#265` (declared `verdict_diagnostic`
output is never written), `#272` (inert `outputs.*.value` on a Docker action), `#271` (adversarial
image installs a different pytest than unit CI).

**Authored by:** W6 · **Greened by:** W7 (`#264`), W8 (`#265` + `#272`, one wave per **D10**),
W9 (`#271`).

Batch B is the **Action / workflow contract** batch, so most of the surface is YAML rather than
Python. Every guard therefore parses the real `action.yml` / `.github/workflows/mergecraft.yml` /
`docker/e2e/run_in_image_adversarial.sh` from disk — there is no runtime object to unit-test for
three of the four issues.

**Tooling decision (W6.1):** no second YAML checker was added.
`scripts/check_action_yml_hygiene.py` scans action manifests for literal `${{ }}` expressions in
description prose and is the wrong tool for job permissions. The repo already has
`tests/ci/workflow_support.py` (`load_workflow`, `job`, `read_text`, `REPO_ROOT`), used by nine
existing workflow-contract suites; W6 **extends that pattern** rather than starting a parallel one.
Likewise `#272` extends the existing `tests/action/test_action_yml_contract.py` (which already
carries a module-scoped `action_yml` fixture) instead of adding a new action-manifest suite.

### Contract → test map

| Contract | Coverage | Layer / class |
|---|---|---|
| **W6.1 / #264** `wait-for-ci` declares a job-level `permissions:` block | `tests/ci/test_mergecraft_workflow_permissions.py::TestWaitForCiPermissions::test_declares_job_level_permissions` | Integration (workflow), error |
| **W6.1 / #264** that block grants `checks: read` | `…::TestWaitForCiPermissions::test_declares_checks_read` | Integration, happy |
| **W6.1** a job-level block does not inherit, so `contents: read` is restated | `…::TestWaitForCiPermissions::test_keeps_contents_read` | Integration, edge |
| **W6.1** W7 must not widen the job past read | `…::TestWaitForCiPermissions::test_grants_nothing_beyond_read_scopes` | Integration, error |
| **W6.1** workflow-level block stays `contents: read` only | `…::TestWorkflowLevelPermissionsUnchanged::test_workflow_level_block_is_contents_read_only` | Integration, happy |
| **W6.1** the `review` job keeps its own scoped block | `…::TestWorkflowLevelPermissionsUnchanged::test_review_job_keeps_its_own_permissions_block` | Integration, happy |
| **W6.1** the poll still hits the check-runs API (else the permission is moot) | `…::TestWaitForCiBehaviourAnchors::test_job_still_queries_the_check_runs_api` | Integration, anchor |
| **W6.1** fail-open contract preserved (the bug is the silent 403, not fail-open) | `…::TestWaitForCiBehaviourAnchors::test_job_stays_fail_open` | Integration, anchor |
| **W6.1** optional W7.1 hardening: stop swallowing stderr on the poll | `…::TestWaitForCiBehaviourAnchors::test_check_runs_poll_does_not_swallow_stderr` | Integration, edge |
| **W6.2 / #265** success + diagnostic → `verdict_diagnostic=<code>` | `tests/cli/test_gha_failure_outputs.py::TestVerdictDiagnosticOutput::test_success_with_diagnostic_writes_the_code` | Functional (E2E `_run_main`), happy |
| **W6.2 / D10** success, no diagnostic → key **present and empty**, never absent | `…::TestVerdictDiagnosticOutput::test_success_without_diagnostic_writes_empty_string` | Functional, edge |
| **W6.2** the raw closed code round-trips unmodified | `…::TestVerdictDiagnosticOutput::test_every_closed_code_round_trips` (5 params) | Functional, happy/table |
| **W6.2** failure path writes it too, before `typer.Exit` | `…::TestVerdictDiagnosticOutput::test_failure_path_still_writes_the_diagnostic` | Functional, error |
| **W6.2** `_set_output(name, "")` already writes `name=` (the empty arm's transport) | `…::TestVerdictDiagnosticOutput::test_set_output_writes_an_empty_value_as_a_present_key` | Unit, edge |
| **W6.3 / #272** Docker action declares no `outputs.*.value` | `tests/action/test_action_yml_contract.py::TestActionYmlHygiene::test_docker_action_declares_no_output_values` | Integration (manifest), error |
| **W6.3** no `${{ }}` survives anywhere under `outputs:` | `…::TestActionYmlHygiene::test_no_expression_survives_in_any_output_block` | Integration, error |
| **W6.3** W8 deletes `value:` only — every description survives | `…::TestActionYmlHygiene::test_every_output_keeps_its_description` | Integration, happy |
| **W6.3 / #265** the `verdict_diagnostic` output stays declared | `…::TestActionYmlHygiene::test_verdict_diagnostic_output_is_declared` | Integration, happy |
| **W6.4 / #271** script pytest pin equals `pyproject.toml`'s | `tests/ci/test_adversarial_image_pytest_pin.py::TestPinsAgree::test_pytest_pin_matches_pyproject` | Integration, error |
| **W6.4** `pytest-asyncio` stays in sync (already is) | `…::TestPinsAgree::test_pytest_asyncio_pin_matches_pyproject`, `…::test_no_runner_package_drifts[pytest-asyncio]` | Integration, happy |
| **W6.4** table form so a newly-added runner pin is covered | `…::TestPinsAgree::test_no_runner_package_drifts` (2 params) | Integration, table |
| **W6.4** the image installs nothing unit CI has never resolved | `…::TestPinsAgree::test_every_script_pin_is_declared_in_pyproject` | Integration, edge |
| **W6.4** both pin anchors are still parseable / exact | `…::TestPinSourcesAreParseable` (3 tests) | Unit, anchor |

### Confirmed-RED assertions (17 xfail, non-strict)

| Target wave | Count | Tests |
|---|---|---|
| **W7** | 5 | 4 × `TestWaitForCiPermissions` + `test_check_runs_poll_does_not_swallow_stderr` (the last is the plan's *optional* hardening, recorded as residual risk rather than a gate) |
| **W8** | 9 | 2 × `TestActionYmlHygiene` (`#272`) + 7 × `TestVerdictDiagnosticOutput` (`#265`, incl. 5 parametrized codes) |
| **W9** | 2 | `test_pytest_pin_matches_pyproject`, `test_no_runner_package_drifts[pytest]` |

`test_no_runner_package_drifts` carries its xfail **per `pytest.param`**, not on the function, so
the `pytest-asyncio` case reports a real pass instead of a misleading `XPASS`.

### Green-today regression guards (48 in the touched files, 14 new)

New green guards: the workflow-level/`review`-job permission anchors, the check-runs and fail-open
behaviour anchors, `_set_output("", …)`'s empty-key transport, the outputs-keep-descriptions and
`verdict_diagnostic`-stays-declared manifest guards, the `pytest-asyncio` parity pair, the
`every_script_pin_is_declared` guard, and the three pin-anchor parse guards.

### Verified-not-drifted (checked while authoring, no test needed)

- `pytest-asyncio` is **`1.3.0` in both** `pyproject.toml` and the adversarial script — only
  `pytest` diverges (`9.0.3` in the image vs `9.1.1` pinned). W9 must bump `pytest` and leave
  `pytest-asyncio` alone.
- `pyproject.toml`'s pytest pin is at **`:56`** (W0's correction of `:54` is right); the script's is
  at **`:25`**. Both are parsed at runtime, so neither line number is baked into an assertion.

### Anchors that contradict the plan (input for W7/W8/W9)

| Plan text | What the code actually shows | Consequence |
|---|---|---|
| W8.2 "thread the diagnostic … into `gha_cmd._run_main`" via "the `RunResult` object" | There is **no `RunResult`**. The carrier is `MainResult` (`src/mergecraft/main.py:109-122`, `@dataclass(slots=True)`), and it has **no diagnostic field at all** | W8 must **add a field** (`verdict_diagnostic: str \| None = None`) to `MainResult` and set it on both return paths (`main.py:1388-1403`), not just read an existing attribute |
| W8.2 anchors the diagnostic at `main_outcome.py:127-139` | Correct, but `_verdict_protocol_publish` returns `(span_attrs, prediction)` and **`prediction` is `None` unless `settings.gates.terminal_verdict == "shadow"`** (`main_outcome.py:140-142`) | The only always-available carrier of the code on the enforce path is `attrs["verdict.diagnostic"]`. W8 should widen the return (or return the `VerdictDiagnostic` itself) rather than reaching through `prediction`, which is empty on the normal path |
| `## Docs ↔ code reconciliation`: "`gha_cmd.py:111-126` writes only `evidence_packet` / `result` / `token`" | Accurate. `_set_output` call sites are `:111` (`evidence_packet`), `:123` and `:126` (`result`), `:135` (`token`) | No change needed |
| W8.1 "`action.yml:187-204`" | Accurate. The three `value:` keys are at **`:189`, `:199`, `:204`**; `runs.using: "docker"` at **`:207`** | No change needed |
| W7.1 "`mergecraft.yml:161`", "`:142-143`", "`:200`" | All accurate: `wait-for-ci:` at `:161` with **no** `permissions:` key (only `name`/`if`/`runs-on`/`timeout-minutes`/`outputs`/`steps`), workflow-level `permissions: {contents: read}` at `:142-143`, `2>/dev/null` on the poll at `:200` | No change needed |
| D10 "empty string when no diagnostic" | `_set_output` already writes `name=` for an empty value (`gha_cmd.py:70-71`), and only skips `::add-mask::` | W8 needs **no new writer** — but it must call `_set_output` unconditionally on the terminal-verdict path, since "write nothing" is the naive implementation that leaves the key absent |

### Escalation log

_(empty)_
