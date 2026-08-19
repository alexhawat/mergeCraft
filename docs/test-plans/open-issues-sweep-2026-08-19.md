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
| C — Analyzer correctness (#270, #269, #268) | W10 | [Batch C](#batch-c--analyzer-correctness-w10) | **reconciled — all green** |
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

### Reconciled assertions (were 17 xfailed → now 17 real passes)

All three implementation waves landed (`a13afc6` W7, `32f1884` W8, `a75d43a` W9) without touching
`tests/`. Every marker was xpassing before the strip, so reconciliation removed markers only — no
assertion was weakened, and nothing escalated.

| Target wave | Count | Reconciled |
|---|---|---|
| **W7** (`a13afc6`, `#264`) | 5 | 4 × `TestWaitForCiPermissions` + `test_check_runs_poll_does_not_swallow_stderr` |
| **W8** (`32f1884`, `#265` + `#272`) | 10 | 2 × `TestActionYmlHygiene` + 8 × `TestVerdictDiagnosticOutput` (incl. 5 parametrized codes) |
| **W9** (`a75d43a`, `#271`) | 2 | `test_pytest_pin_matches_pyproject`, `test_no_runner_package_drifts[pytest]` |

The W6 table above counted W8 as 9 and W7's stderr case as *optional*; the true instance counts are
10 and 5 (17 total either way). W7 landed the stderr hardening despite the plan marking it optional,
so `test_check_runs_poll_does_not_swallow_stderr` is now a plain green guard, not residual risk.
`test_no_runner_package_drifts`'s per-`pytest.param` xfail collapsed back into a plain
`@pytest.mark.parametrize("package", ["pytest", "pytest-asyncio"])`.

Docstring narration that described the pre-fix defect in the present tense
(`TestVerdictDiagnosticOutput`'s "`MainResult` has no field for it … red today", the stderr test's
"non-strict xfail either way") was rewritten to state the contract. The now-unnecessary
`# type: ignore[call-arg]` on the failure-path `MainResult(...)` was dropped (mypy strict flags
unused ignores).

### Post-reconciliation contract audit (Batch B)

- **The `verdict_diagnostic` tests cover the `$GITHUB_OUTPUT` write, not the dataclass field.**
  Every case in `TestVerdictDiagnosticOutput` monkeypatches `mergecraft.main.main`, runs the real
  `asyncio.run(_run_main())`, and asserts against the parsed `$GITHUB_OUTPUT` file. Constructing
  `MainResult(verdict_diagnostic=…)` is only the *input* fixture; a `MainResult` that merely holds
  the string while `_run_main` writes nothing fails all of them. The transport under test is
  `gha_cmd.py:120` — `_set_output("verdict_diagnostic", result.verdict_diagnostic or "")`.
- **D10's empty arm asserts presence, not absence of a crash.**
  `test_success_without_diagnostic_writes_empty_string` asserts `"verdict_diagnostic" in entries`
  *and* `entries["verdict_diagnostic"] == ""`. Its transport premise is separately pinned by
  `test_set_output_writes_an_empty_value_as_a_present_key`, which asserts the file content is
  exactly `verdict_diagnostic=\n`.
- **Nothing pins W8's particular plumbing.** No assertion names `_verdict_protocol_publish`,
  `diagnostic_attrs`, or `verdict.diagnostic`. W8 deliberately did *not* widen
  `_verdict_protocol_publish`'s 2-tuple return (that would have broken
  `tests/evidence/test_verdict_shadow.py`) and read the span-attrs dict instead; a later refactor
  that widens the return, or threads a `VerdictDiagnostic` object, keeps this batch green as long
  as the output is written on both `_finalize` return paths.
- **Producer side — closed.** The gap first recorded here (nothing proved `_finalize` actually
  populates `MainResult.verdict_diagnostic`, so a regression that stopped *computing* the code
  would leave the write-path tests green while the output silently went empty) is now covered by
  `tests/test_main_phases.py::TestFinalizeCarriesTheVerdictDiagnostic` — see below. `#265` is
  covered end to end: producer → `MainResult` → `$GITHUB_OUTPUT`.

### Producer-half coverage for `#265` (`TestFinalizeCarriesTheVerdictDiagnostic`)

Added to `tests/test_main_phases.py`, the existing `_finalize` phase suite, so it uses the same
`tests/support/run_main_harness.py` vehicle as `test_main_result_is_unchanged_for_each_run_outcome`
— a real `main()` run against scripted collaborators, no new pattern. **10 tests, all green**: W8's
producer half was correctly implemented, nothing was red, and no `xfail` was needed.

| Contract | Test | Layer / class |
|---|---|---|
| The `passed` return carries the computed code | `test_success_path_carries_the_computed_code` | Functional, happy |
| The non-`passed` return is a separate `return` and must not drop it | `test_failure_path_carries_the_computed_code` | Functional, happy |
| Two different failures on the same branch keep *different* codes | `test_policy_rejection_is_distinguishable_from_provider_failure` | Functional, edge |
| `enforce` and `shadow` deposit the same code | `test_enforce_and_shadow_deposit_the_same_code` (3 params) | Functional, seam |
| Every completed run deposits a closed-vocabulary code | `test_every_completed_run_deposits_a_closed_code` | Functional, table |
| A run that never classified carries a falsy value, never a fabricated code | `test_runs_that_never_classified_carry_no_code` (3 params) | Functional, D10 empty arm |

Notes on what these pin and what they deliberately do not:

- **The enforce/shadow seam agrees.** `_verdict_protocol_publish` returns `prediction` only when
  `terminal_verdict == "shadow"`, which is why W8 read the always-populated carrier instead. The
  parity test runs each of `passed` / `failed` / `inconclusive` under both modes and asserts the
  same code lands, so an implementation that reached the diagnostic through the shadow-only carrier
  fails under the (default) `enforce` mode rather than passing by luck.
- **D10's empty arm, producer end.** `timed_out` / `configuration_error` / `infra_error` leave
  through `main()`'s outer handler and never reach the verdict classification — the same asymmetry
  `test_main_result_is_unchanged_for_each_run_outcome` already pins for the evidence packet. Those
  three assert the value is *falsy* (`None` or `""` both satisfy the consumer, which writes a
  present-but-empty key either way), never a fabricated code.
- **No plumbing is named.** No assertion mentions `diagnostic_attrs`, `verdict.diagnostic`, or
  `_verdict_protocol_publish`; everything goes through `main()` and `MainResult`. Threading the
  diagnostic on the prediction object, a widened publish helper, or a third carrier keeps these
  green.
- **Codes are asserted as literals** (`approved`, `provider_failure`, `policy_rejection`) rather
  than recomputed from the predictor, so a change to the classification policy has to be a
  deliberate test edit rather than a silently-tracking tautology. Membership in the closed
  `VerdictDiagnostic` vocabulary is checked separately.

### Escalation log

_(empty)_

---

## Batch C — Analyzer correctness (W10)

**Issues:** #270 (OSV fixed-version regex), #269 (`base_comparison_available` inversion),
#268 (ruff-format finding attribution).
**Implementation waves:** W11 (#270), W12 (#269), W13 (#268).
**Binding decision:** **D19** — analyzer waves fix parsers/adapters/scope only. No new analyzer,
no catalog row. Nothing in this batch asserts a catalog string, a manifest id that does not
already ship, or a severity-gate row, so `make catalog-check` stays out of the loop.

**Anchors re-grepped, not trusted from the plan body** (W0 corrected two of the three):

| Issue | Anchor used | Plan text | Verdict |
|---|---|---|---|
| #270 | `analyzers/parsers/osv_json.py:82` | same | matches |
| #269 | `analyzers/scope.py:234-238` → consumer `analyzers/pipeline.py:361,376` | W12.1 still says `scope.py:232`; W12.2 still says `pipeline.py:276-280` | **stale in the wave body** — the Traceability table is right |
| #268 | `analyzers/adapters.py:85-119` | W13.1 still says `:85-127` | **stale in the wave body** — the Traceability table is right |

### Files

| File | Status | Issue |
|---|---|---|
| `tests/analyzers/parsers/test_osv_json.py` | **new** | #270 |
| `tests/analyzers/test_scope.py` | extended (pure function + pipeline consumer) | #269 |
| `tests/analyzers/test_adapters_ruff_format.py` | **new** | #268 |

### Contract → test map

| Contract | Test | Layer / class | Marker |
|---|---|---|---|
| A real `N.N.N` fix version is accepted | `test_real_three_component_version_is_accepted` (4 params) | Unit, happy | green |
| A single-character separator substitution is rejected | `test_wildcard_separator_is_rejected[1.2x3, 1.2X3, 1.2-3, 1.2_3, "1.2 3", 1.2/3]` | Unit, edge | xfail W11 |
| The wildcard matching a **digit** is rejected | `test_wildcard_separator_is_rejected[1.234, 1.2345, 10.234, 1.2x34]` | Unit, boundary | xfail W11 |
| Malformed versions stay rejected after the escape | `test_malformed_version_stays_rejected` (11 params) | Unit, boundary | green |
| No `fixed` event / non-`ECOSYSTEM` range yields nothing | `test_missing_fixed_event_yields_no_version`, `test_non_ecosystem_range_is_ignored` | Unit, edge | green |
| The reviewer-visible remediation names a real version | `test_remediation_names_a_real_fix_version` (2 params) | Integration, happy | green |
| No fabricated `Upgrade to 1.2x3 or later` | `test_remediation_is_omitted_for_a_malformed_fix_version` (2 params) | Integration, error | xfail W11 |
| Clearly-malformed versions already produce no remediation | `test_remediation_already_omitted_for_clearly_malformed_versions` (2 params) | Integration, boundary | green |
| Online + `full` ⇒ base comparison available | `test_base_comparison_available_is_true_when_online_and_full` | Unit, happy | xfail W12 |
| Offline + `full` ⇒ not available | `test_base_comparison_available_is_false_when_offline_and_full` | Unit, error | xfail W12 |
| `baseComparison != "full"` short-circuits regardless of `offline` | `test_base_comparison_available_is_false_unless_comparison_is_full` (6 params) | Unit, table | green |
| **Consumer:** an online `full` run reaches `annotate_introduced_by_pr` with a truthy `base_run_performed` | `test_online_full_comparison_reaches_the_annotator_as_performed` | Integration, seam | xfail W12 |
| **Consumer:** an offline run never claims a base run | `test_offline_full_comparison_never_claims_a_base_run` | Integration, seam | xfail W12 |
| Only the second scoped file reformatting cites the second file | `test_only_the_second_file_reformatting_cites_the_second_file` (2 params) | Integration, the bug | xfail W13 |
| Both files reformatting yield one finding each (W13.1) | `test_both_files_reformatting_yield_one_finding_each` (2 params) | Integration, multi-file | xfail W13 |
| A clean *middle* file must not absorb the finding | `test_third_file_reformatting_is_not_attributed_to_the_first` (2 params) | Integration, edge | xfail W13 |
| The one multi-file case today gets right must survive | `test_first_of_two_files_reformatting_cites_the_first` | Integration, regression | green |
| A single-file run still reports that file | `test_single_file_run_still_reports_that_file` | Integration, happy | green |
| Exit 0 ⇒ no findings | `test_clean_run_reports_nothing` | Integration, happy | green |
| No scoped files ⇒ no findings | `test_no_scoped_files_reports_nothing` | Integration, edge | green |
| Finding shape (tool, `rule_id: format`, line 1, message) is stable — D19 | `test_format_finding_metadata_is_stable` | Integration, contract | green |

### Confirmed-RED assertions (22 xfails, verified with `--runxfail`)

All 22 fail on the assertion, never on a stub or import error:

- **W11 (12)** — `_fixed_version("1.2x3")` returns `"1.2x3"`; `_fixed_version("1.234")` returns
  `"1.234"`; and `parse_osv_json` turns both into `Upgrade to <garbage> or later`.
- **W12 (4)** — `base_comparison_available(base_comparison="full", offline=False)` is `False`
  (expected `True`) and `offline=True` is `True` (expected `False`); the pipeline consumer records
  `[False]` on an online `full` run and `[True]` offline.
- **W13 (6)** — `_run_ruff_format_check` returns `['pkg/a.py']` when only `pkg/b.py` would
  reformat, and one finding when two files would.

### Green-today regression guards (41 assertions)

The OSV boundary table (`1.2`, `1.23`, `1.2.3.4`, `1.2..3`, `1.2xy3`, `v1.2.3`, `1.2.3-rc1`,
`1.2.x`, `abc`, `""`) exists so W11's escape cannot *narrow* the guard past `N.N.N` or start
admitting a prerelease. `1.23` is the interesting one: it is exactly one digit short of slipping
through the wildcard, so it pins the boundary from the other side. The `base_comparison != "full"`
table (6 params) guards the short-circuit W12 must leave alone. The ruff-format guards pin the
single-file and clean-run shapes plus the finding metadata, so W13 cannot buy per-file attribution
by changing severity, rule id, or line.

### What the unescaped dot actually admits

`re.fullmatch(r"\d+\.\d+.\d+", fixed)` — the third separator is a wildcard, so the guard admits
**two** families, only one of which the issue names:

1. **Any single non-newline character** in the separator slot: `1.2x3`, `1.2-3`, `1.2 3`, `1.2/3`,
   `1.2_3`, and also `1.2x34` (the trailing `\d+` is not length-bound). Two characters do not fit —
   `1.2xy3` is correctly rejected — so the hole is exactly one character wide.
2. **A digit**, because `.` matches digits too. Any two-component version with **three or more**
   digits after the dot parses as three components: `1.234` → `1` `.` `2` `[3]` `4`. `1.23` fails
   (nothing is left for the trailing `\d+`), so ≥ 3 trailing digits is the boundary. This family is
   the more dangerous one in practice — `1.234` is a plausible real version string, and OSV
   ecosystems that use two-component versions would silently hand the reviewer a fabricated
   three-component "fix".

`\n` is not admitted (`.` excludes newline), and `1.2.3.4` / `1.2..3` are rejected before and after
the fix.

### Notes for W11 / W12 / W13

- **W12's wave text points at `scope.py:232` and `pipeline.py:276-280`.** Both are stale; the live
  lines are `scope.py:238` (`return offline` inside `base_comparison_available`) and
  `pipeline.py:361` (the call) → `pipeline.py:376` (`base_run_performed=base_run` passed into
  `_apply_baseline_suppression`, which forwards to `annotate_introduced_by_pr` at `:131` / `:157`).
  W12 is a one-word change at `scope.py:238`; nothing in `pipeline.py` needs to move.
- **The #269 consumer test drives the real `run_analyzer_pipeline`** (`detect_enabled`,
  `run_adapter`, and `_analyzers_settings` stubbed; `baseComparison: full`, empty diff), and records
  what `annotate_introduced_by_pr` is actually handed. It is the same seam-pinning technique as
  `test_shell_disabled_split.py::test_pipeline_forwards_the_shell_to_the_adapter`. The annotation
  *output* is not observable here — `is_new_in_base` defaults to `False`, so both branches yield
  `"unknown"` — which is precisely why the bug survived: only the argument is observable.
- **W13 may choose either strategy.** The stub decides its verdict from the file paths in
  `plan.argv`, so it answers correctly for a single combined invocation *and* for one run per file.
  Per-file attribution **is** achievable from today's single invocation: `run_plan` returns the
  combined stdout/stderr on `AnalyzerOutcome.output`, and `ruff format --check` prints one
  `Would reformat: <path>` line per file. Per-file runs are the fallback, not a requirement.
- **Paths reach ruff as absolute strings** (`expand_analyzer_argv` joins each relative path onto
  `repo_root`), so W13 must relativize whatever it parses. Each attribution test is parametrized
  over an absolute and a repo-relative `Would reformat:` line so neither form may be assumed.
- **The stub sets `output_path=None`.** If W13 prefers the persisted output file over
  `outcome.output`, it must tolerate a missing path — or these tests need a one-line amendment
  (escalate rather than edit them in an implementation wave).
- **Deliberately not pinned (resolved — see below):** what should happen when `ruff format --check`
  exits non-zero with no `Would reformat:` line at all (a ruff-side parse error). The correct answer
  differed between the two strategies, so pinning it would have picked the implementation for W13.
  W13 decided; the decision is now covered by `TestRuffFailureFallback`-equivalent cases in
  `tests/analyzers/test_adapters_ruff_format.py`.

### Reconciled assertions (were 22 xfailed → now 22 real passes)

All three implementation waves landed (`dde1e94` W11, `4695e6e` W12, `eddd8f7` W13) without touching
`tests/`. Every marker was xpassing before the strip, so reconciliation removed markers only — no
assertion was weakened, and nothing escalated.

| Target wave | Count | Reconciled |
|---|---|---|
| **W11** (`dde1e94`, `#270`) | 12 | `test_wildcard_separator_is_rejected` (10 params) + `test_remediation_is_omitted_for_a_malformed_fix_version` (2 params) |
| **W12** (`4695e6e`, `#269`) | 4 | both `base_comparison_available` unit cases + both pipeline-consumer seam cases |
| **W13** (`eddd8f7`, `#268`) | 6 | the three attribution tests × the absolute/relative parametrization |

Present-tense defect narration was rewritten to state the contract: the `test_osv_json.py` module
docstring and both case-table comments, the `#269` section comment in `test_scope.py`, the
`test_adapters_ruff_format.py` module docstring, and four docstrings that named a wave number
(`W11 must not narrow…`, `W13 must not lose it`, `W13 changes attribution only`, `untouched by W12`).
The stale `adapters.py:85-119` anchor in the module docstring is now `:85-148`.

**Per-file counts after reconciliation — 69 passed, 0 xfail, 0 xpass:**
`test_osv_json.py` 33, `test_scope.py` 19, `test_adapters_ruff_format.py` 17 (11 pre-existing + 6
new fallback cases). Full `tests/analyzers` + `tests/review`: **664 passed**, no xfail, no xpass.

### W13's tool-failure fallback — the decision, now covered

**The decision.** A non-zero exit carrying no parseable `Would reformat:` line means ruff itself
failed (bad config, syntax error, unexpected output shape), not that a file is unformatted. W13
emits **one finding at `scoped_files[0]`** rather than returning nothing, so a broken analyzer
cannot read as a clean bill of health (`adapters.py:138-148`).

**Why this needed pinning beyond "it works".** `scoped_files[0]` is the exact misattribution #268
exists to fix. Left untested, a future refactor could route parseable output back through this arm —
restoring the bug — and every #268 attribution test could still be satisfied by an implementation
that happened to order `pkg/a.py` first. The reachability guard closes that door.

| Contract | Test | Layer / class |
|---|---|---|
| Tool failure with unparseable output cites `scoped_files[0]` | `test_tool_failure_without_parseable_output_reports_the_first_scoped_file` (3 params: invocation error, empty output, summary line only) | Integration, error |
| **The fallback is unreachable while a `Would reformat:` line parses** — failure text naming `pkg/a.py`, exit 2, and one parseable line naming `pkg/b.py` ⇒ the finding cites `pkg/b.py` | `test_fallback_is_unreachable_while_would_reformat_lines_parse` | Integration, #268 regression guard |
| No scoped files ⇒ no finding (the arm must not index into an empty list) | `test_tool_failure_with_no_scoped_files_reports_nothing` | Integration, edge |
| One failure signal, not one per scoped file | `test_tool_failure_fallback_reports_exactly_one_finding` | Integration, edge |

**Verdict on the contract: the fail-loud direction is right, the message is not.** Emitting rather
than silencing is the correct call — an analyzer that fails open on its own crash is worse than a
false positive, and the reviewer surface has no other channel for "this tool broke". But the
fallback reuses `_format_finding(..., message="File would be reformatted by ruff format")`, so a
ruff *crash* is reported to the reviewer as a *formatting violation* in a file that may be perfectly
formatted — a factually false claim, and the same class of misattribution #268 is about, one level
up. A message naming the real condition (`ruff format --check failed; output could not be parsed`)
would keep the fail-loud property while telling the truth. **This is a message-text change in
`src/`, out of scope for a test-author wave, and it is not encoded as a failing test** — the four
cases above pin W13's behaviour as shipped. Flagged for Batch C Final or a follow-up issue.

### Post-reconciliation contract audit (Batch C)

- **The absolute/relative parametrization still holds and now proves more.** All three attribution
  tests remain `@pytest.mark.parametrize("emit_absolute", [False, True])`, driving the stub to emit
  `Would reformat: /abs/path/pkg/b.py` and `Would reformat: pkg/b.py` against the same adapter.
  During reconciliation the assertion helper `_paths()` was **tightened**: it previously ran each
  finding's path back through the adapter's own `resolve_repo_relative_path` before comparing, which
  meant an implementation that leaked absolute paths into findings would still have passed. It now
  asserts `f.path` **raw**, so the absolute arm genuinely proves the adapter relativizes. Both arms
  pass, confirming W13's relativization handles the form ruff actually emits (absolute, since
  `expand_analyzer_argv` joins onto `repo_root`) *and* the repo-relative form.
- **Nothing names `resolve_repo_relative_path`.** That tightening also removed the suite's only
  import of it; `rg resolve_repo_relative_path tests/` returns nothing. Attribution is asserted as
  observed finding paths, so replacing the helper, inlining it, or switching to `Path.relative_to`
  keeps the file green as long as findings stay repo-relative.
- **Nothing names the parse strategy either.** No assertion mentions `Would reformat` as an
  implementation detail of the adapter — the string appears only in *stub output*, i.e. in what ruff
  is simulated as printing. An implementation that switched to per-file `ruff format --check` runs,
  or to `--output-format json`, still satisfies every attribution case, because the stub answers
  from the paths in `plan.argv`. The one exception is deliberate:
  `test_fallback_is_unreachable_while_would_reformat_lines_parse` necessarily distinguishes
  parseable from unparseable output, which is the contract it exists to pin.
- **The `output_path=None` caveat is now closed.** The W10 note warned that if W13 preferred the
  persisted output file over `outcome.output`, the stubs would need amending. W13 read
  `outcome.output` (`adapters.py:123`), so no amendment was needed and no escalation occurred.
- **`_fixed_version` is exercised directly and through `parse_osv_json`.** The unit table and the
  remediation-string integration cases would both have to be edited to re-admit a fabricated
  version, so a regression cannot hide behind either layer alone.
- **#269's seam guard survives the fix.** `test_online_full_comparison_reaches_the_annotator_as_performed`
  still drives the real `run_analyzer_pipeline` and records what `annotate_introduced_by_pr` is
  handed; the annotation *output* remains unobservable (`is_new_in_base` defaults to `False`), which
  is why the argument-level assertion is the only thing that can catch a re-inversion one layer up.

### Escalation log

_(empty)_

---

## Batch D — Agents + approve gate (W14)

**Issues:** #222 (Codex `default_permissions` nested under `[model_providers.*]`), #261
(`structured_handoff` casefold detect + exact-case split), #262 (ensemble disagreement drops
secondary-only findings), #273 (`to_usage()` double-counts OpenAI cached tokens), #263
(`submit_review_verdict(approve)` ignores unverified blocking analyzer findings).
**Implementation waves:** W15 (#222), W16 (#261), W17 (#262), W18 (#273), W19 (#263).
**Binding decisions:** **D17** (root keys before tables), **D15** (union on disagreement), **D16**
(OpenAI cached tokens are inclusive), **D12** (approve fails closed on unverified blockers).

**Anchors re-grepped, not trusted from the plan body:**

| Issue | Anchor used | Plan text | Verdict |
|---|---|---|---|
| #222 | `agents/codex.py:506-508` (`_append_custom_provider_lines` then `_append_read_only_mcp_network_lines`; the root key is written at `:460`) | same | matches |
| #261 | `agents/structured_handoff.py:44-45` | same | matches |
| #262 | `agents/ensemble.py:210-214` (the disagreement `return`; `merged_findings=tuple(left.findings)` at `:212`) | W17.1 `:210-214`, Traceability `:211-212` | matches |
| #273 | `agents/_stream_consumer.py:181` | same | matches |
| #263 | `mcp/verdict.py:276-313` (`_confirmed_findings_from_state`), `:395-413` (the approve branch) | W19.1 said `~377`; the Docs↔code table said `:377+`; Traceability said `:276-292,395+` | **stale — corrected in the plan by W14** |

### Files

| File | Status | Issue |
|---|---|---|
| `tests/agents/test_codex_custom_provider.py` | extended | #222 |
| `tests/agents/test_structured_handoff.py` | extended | #261 |
| `tests/agents/test_ensemble.py` | extended | #262 |
| `tests/agents/test_stream_usage_cache.py` | **new** | #273 |
| `tests/review/test_terminal_verdict_policy.py` | extended (validator + live tool + finalize) | #263 |
| `tests/mcp/test_submit_review_verdict.py` | extended (tool surface) | #263 |
| `tests/agents/test_opencode_session_usage.py` | **new at DF** — second #273 ingress; reconciled after W18b (markers stripped, precedence pinned) | #273 |

### Contract → test map

| Contract | Test | Layer / class | Marker |
|---|---|---|---|
| `default_permissions` parses at the TOML **top level** with custom-provider env active | `test_default_permissions_stays_a_root_key_with_custom_providers` (3 params) | Unit, the bug | xfail W15 |
| An empty `[model_providers]` table (partial pair) also swallows the key | `test_default_permissions_survives_a_partial_provider_pair` | Unit, edge | xfail W15 |
| No key the writer means as **document root** may appear after the first table header | `test_no_root_key_is_emitted_after_the_first_table` | Unit, invariant | xfail W15 → **rewritten at DF** (see escalation log) |
| The scope tracker behind that invariant flags the pre-W15 emission order | `test_root_key_scope_helper_flags_the_pre_w15_emission_order` | Unit, guard-on-the-guard | green (added at DF) |
| `[permissions.<profile>]` tree survives the reorder | `test_permission_profile_tables_are_unchanged_with_custom_providers` | Unit, regression | green |
| The no-provider path is already correct | `test_default_permissions_is_already_a_root_key_without_custom_providers` | Unit, boundary | green |
| Provider blocks keep `base_url` / `env_key` / `wire_api` (#71, convention 7) | `test_custom_provider_blocks_keep_their_own_keys` | Unit, regression | green |
| A mixed-case marker parses its findings | `test_mixed_case_marker_parses_the_findings_payload` (5 casings) | Unit, the bug | xfail W16 |
| A mixed-case marker is stripped from the reasoning | `test_mixed_case_marker_is_stripped_from_the_reasoning` (5 casings) | Unit, edge | xfail W16 |
| A mixed-case marker with `[]` yields no findings and no raise | `test_mixed_case_marker_with_an_empty_array_yields_no_findings` (5 casings) | Unit, boundary | xfail W16 |
| The documented lowercase casing still parses | `test_lowercase_marker_still_parses` | Unit, regression | green |
| No marker ⇒ prose only | `test_no_marker_at_all_yields_prose_only` | Unit, edge | green |
| A genuinely malformed tail still raises with its message contract | `test_malformed_tail_still_raises_a_value_error`, `test_non_array_tail_still_raises_a_value_error` | Unit, error | green |
| **Non-ASCII** reasoning before the marker does not shift the split | `test_non_ascii_reasoning_before_the_marker_parses` (5 casings + lowercase) | Unit, unicode | green (added at DF) |
| The same with an empty `[]` payload — the shape W16 hand-verified | `test_non_ascii_reasoning_with_an_empty_payload_parses` | Unit, boundary | green (added at DF) |
| A right-only finding survives disagreement | `test_disagreement_keeps_a_right_only_finding` | Unit, the bug | xfail W17 |
| Both sides' exclusive findings survive | `test_disagreement_unions_both_sides` | Unit, D15 | xfail W17 |
| The union deduplicates by `_finding_key` | `test_disagreement_union_deduplicates_a_shared_finding` | Unit, boundary | xfail W17 |
| An empty left side does not swallow the right side | `test_disagreement_with_an_empty_left_side_keeps_the_right_findings` | Unit, edge | xfail W17 |
| `judge_dispatch` is retained (D15) | `test_disagreement_still_dispatches_the_judge` | Unit, D15 | green |
| Disagreement claims no confidence boost | `test_disagreement_claims_no_confidence_boost` | Unit, regression | green |
| The agreement path is untouched (#238) | `test_agreement_path_is_untouched_by_the_union` | Unit, regression | green |
| A one-model run short-circuits | `test_single_model_run_is_returned_unmerged` | Unit, edge | green |
| OpenAI cached tokens are **not** added to `input_tokens` | `test_openai_cached_tokens_are_not_added_to_input_tokens` (2 shapes × `replace`/`absorb`) | Unit, the bug | xfail W18 |
| An OpenAI payload with a cache-**write** count still adds the write | `test_openai_cache_write_stays_additive_while_reads_do_not` | Unit, D16 split | xfail W18 |
| **Consumer:** `codex turn.completed` through the real handler | `test_codex_turn_completed_reports_inclusive_cached_tokens` (2 shapes) | Integration, seam | xfail W18 |
| `cache_read_tokens` still reports the cached count | `test_openai_cached_tokens_are_still_reported` (2 shapes) | Unit, guard | green |
| Anthropic `cache_read_input_tokens` stays additive | `test_anthropic_cache_read_stays_additive` (`replace`/`absorb`) | Unit, the asymmetry | green |
| Anthropic reads **and** writes both add | `test_anthropic_full_shape_sums_both_cache_buckets` | Unit, boundary | green |
| A native Anthropic field wins over an OpenAI details block | `test_anthropic_native_field_wins_over_an_openai_details_block` | Unit, provenance | green — **cross-locked to the session path at W18b DF** |
| No cache fields ⇒ `input_tokens` untouched, `cache_*` `None` | `test_no_cache_fields_leaves_input_tokens_untouched` | Unit, edge | green |
| T2's extractor is the provenance signal and must not be deleted | `test_openai_extractor_still_recognises_both_shapes` | Unit, guard | green |
| **Consumer:** Claude `message_start` + `result` keeps Anthropic accounting | `test_claude_result_event_keeps_anthropic_accounting` | Integration, seam | green |
| An empty stream reports no usage | `test_empty_stream_still_reports_no_usage` | Integration, edge | green |
| **Second ingress:** the opencode HTTP session path does not add inclusive cached tokens | `test_openai_cached_tokens_are_not_added_to_session_input_tokens` (2 shapes × `info`/`usage`) | Unit, the bug | green (**marker stripped at W18b DF**) |
| …including under the short `input` / `output` aliases that path accepts | `test_openai_cached_tokens_under_the_short_input_alias` (2 shapes) | Unit, alias | green (**marker stripped at W18b DF**) |
| **Both cache shapes present** resolve **native-first and additive** on the session path — the precedence W18b chose, pinned as a decision | `test_both_cache_shapes_resolve_native_first_by_deliberate_choice` (2 details keys × `info`/`usage`) | Unit, precedence | green (added at W18b DF) |
| The session path's Anthropic-native arm stays additive | `test_anthropic_native_cache_read_stays_additive` (`info`/`usage`) | Unit, the asymmetry | green (added at DF) |
| The session path still records `cache_read_tokens` | `test_openai_cached_tokens_are_still_reported` (2 shapes) | Unit, guard | green (added at DF) |
| No cache fields / no usage on the session path | `test_no_cache_fields_leaves_session_input_tokens_untouched`, `test_session_without_usage_reports_no_usage` | Unit, edge | green (added at DF) |
| `approve` is rejected for an unverified blocking analyzer finding | `test_approve_is_rejected_for_an_unverified_blocking_analyzer_finding` (Critical, Major) | Unit, the bug | xfail W19 |
| **Consumer:** the live `ToolContext`-derived state also fails closed | `test_live_submit_approve_is_rejected_for_an_unverified_blocker` | Integration, seam | xfail W19 |
| An `approve` banked before `run_analyzers` becomes unusable at finalize | `test_approve_recorded_before_analyzers_becomes_unusable` | Functional, revalidation | xfail W19 |
| **Consumer:** the MCP tool rejects and records nothing | `test_approve_is_rejected_when_a_blocker_was_never_verified` (Critical, Major) | Integration, tool | xfail W19 |
| A non-blocking unverified finding still allows `approve` | `test_approve_survives_a_non_blocking_unverified_analyzer_finding`, `test_approve_is_recorded_when_the_analyzer_findings_are_non_blocking` | Unit + tool, legitimate approve | green |
| An empty analyzer run / no analyzer run still allows `approve` | `test_approve_survives_an_empty_analyzer_run`, `test_approve_is_recorded_when_no_analyzer_run_happened` | Unit + tool, boundary | green |
| A **withdrawn** blocker must not block (D12's escape hatch) | `test_approve_survives_a_withdrawn_blocking_finding` | Unit, D12 | green |
| The new walk belongs to the approve branch only | `test_request_changes_is_unaffected_by_an_unverified_blocker` | Unit, scope | green |
| `apply_causality_policy` runs before the gate | `test_a_pre_existing_blocker_is_downgraded_before_the_gate` | Unit, policy | green |

### Confirmed-RED assertions (37 xfails, verified with `--runxfail`)

All 37 fail on the assertion, never on an import or a stub:

- **W15 (5)** — with one indexed pair, two indexed pairs, or the singleton alias, `tomllib.loads`
  finds `default_permissions` at `model_providers.<id>.default_permissions` and
  `parsed["default_permissions"]` is `None`. A partial pair puts it at
  `model_providers.default_permissions`. The general invariant reports `["default_permissions"]` as a
  stray root key after the first table header.
- **W16 (15)** — every mixed-case marker (`upper`, `title`, `mixed`, `upper-head`, `upper-tail`)
  raises `ValueError: … not valid JSON: Expecting value: line 1 column 1 (char 0)` for the populated
  array, the empty array, and the reasoning-strip arm alike.
- **W17 (4)** — `merged_findings` is `(left_only,)` when the right model found `pkg/billing.go`, and
  `()` when the left model found nothing at all.
- **W18 (7)** — `to_usage().input_tokens` is `140` (expected `100`) for both OpenAI shapes through
  both `replace_usage` and `absorb_usage`, `165` (expected `125`) with a cache-write count, and
  `140` through the real `codex` `turn.completed` handler.
- **W19 (6)** — `validate_submission` accepts `approve` with an unverified Critical or Major in
  `analyzer_run.findings`; `submit_review_verdict` records a `TerminalSubmission`;
  `finalize_agent_result` reports `terminal_submission_received=True`.

### Green-today regression guards (28 new assertions)

Four of these five fixes have an over-correcting failure mode, so each is guarded from the other
side:

- **#222** — the `[permissions.<profile>]` tree and the provider blocks are pinned separately, so
  W15 must *reorder* emission rather than move keys into or out of tables. The no-provider arm
  proves the same line already parses correctly at the top level, which is what makes this a
  key-ordering bug and not a missing key.
- **#261** — the two error arms (`not valid JSON`, `must be a JSON array`) pin the message contract,
  so a fix cannot buy the mixed-case case by swallowing genuinely malformed tails.
- **#262** — `judge_dispatch` is asserted present on the same disagreement input the union tests
  use (D15 is explicit the judge stays), and the dedup arm blocks the naive
  `tuple(left) + tuple(right)`.
- **#273** — the Anthropic arms are the point; see the note below.
- **#263** — five arms pin the *legitimate* approve: non-blocking findings, an empty analyzer run,
  no analyzer run at all, a withdrawn blocker, and a pre-existing Critical that
  `apply_causality_policy` downgrades to `Minor`. Without them, "reject when `analyzer_run.findings`
  is non-empty" would pass every red.

### The #273 asymmetry — separable today, no provider flag needed

D16 hints W18 may need a flag. It does need **one bit of state**, but the provenance is already
unambiguous in the current code, so no provider identity or driver-level flag has to be threaded in:

- `absorb_usage` / `replace_usage` resolve `cache_read` as
  `cache_read_input_tokens or cacheReadTokens or _extract_openai_cached_tokens(payload) or 0`. The
  Anthropic-native fields are consulted **first**, so at the moment `cache_read` is assigned the
  writer knows which branch produced it. `test_anthropic_native_field_wins_over_an_openai_details_block`
  pins that ordering precisely so the fix can rely on it.
- The cheapest shape is a sibling field on the accumulator (e.g. `cache_read_is_inclusive: bool`)
  set at the same two assignment sites and read only by `to_usage()`. `AgentUsage` needs no new
  field — `cache_read_tokens` keeps reporting the count either way.
- **The one genuinely ambiguous case is a mixed stream**: `absorb_usage` accumulates across events,
  so a run whose `message_start` were Anthropic-shaped and whose `message_delta` were OpenAI-shaped
  would carry one flag for two provenances. No live driver does this — Claude is the only
  `absorb_usage` caller and it is Anthropic-native throughout, while every OpenAI-shaped provider
  arrives through a single terminal `replace_usage`. This suite does **not** pin the mixed case, on
  purpose: pinning it would force W18 to pick a resolution rule for a shape no provider emits. Both
  accumulator methods are covered independently instead.

### Notes for W15 / W16 / W17 / W18 / W19

- **#263's rejection reason: reuse `REJECTION_APPROVE_CONFIRMED_BLOCKER`**
  (`approve_with_confirmed_blocker`). The string *is* pinned by existing tests —
  `tests/review/test_terminal_verdict_policy.py:73` defines `_REASON_APPROVE_CONFIRMED_BLOCKER` and
  four tests assert it — but only for the **verified**-blocker path
  (`test_agent_approve_with_verified_blocker_fails_structurally`,
  `test_live_confirm_blocks_approve_via_verified_ids`,
  `test_live_agent_confirm_blocks_approve_without_analyzer_findings`,
  `test_confirm_survives_analyzer_rerun`). Nothing distinguishes "unverified" from "verified", so
  reusing the constant leaves all four intact and satisfies the plan's stated preference for one
  reason. W19 must **not** add a new constant: the W14 reds assert this exact string at the
  validator, at the tool, and through `finalize_agent_result`.
- **#263 has no live `withdrawn_fingerprints` producer.** `validation_state_from_tool_state`
  hardcodes `withdrawn_fingerprints=set()` (`verdict.py:332`), and the withdrawn-findings memory
  suppresses findings earlier, in `analyzers/pipeline.py:355`. The withdrawn arm is therefore
  asserted at the `validate_submission(state=…)` boundary with a hand-built state. It is green today
  (the approve branch ignores `analyzer_run.findings` entirely) and becomes load-bearing after W19.
- **#263's finalize arm goes through `revalidate_recorded_submission`.** An approve banked *before*
  `run_analyzers` must not survive it; the same machinery already handles the failed-static-check
  case (`test_approve_then_failed_static_check_is_unusable_at_finalize`), so W19 should need no new
  revalidation hook — only the widened walk.
- **#222's tests depend on the permission-profile branch being live.** `_permission_profiles_active`
  asserts `_codex_use_permission_profiles(ctx)` before each nesting assertion, because with profiles
  off the key is never emitted and "not nested" would hold for the wrong reason. The autouse env
  fixture now also clears `MERGECRAFT_CODEX_SANDBOX`, which would otherwise flip `_sandbox_mode` off
  `read-only` and silently disable the branch.
- **#222 is asserted through `tomllib`, never by substring.** `default_permissions =` *is* present in
  the broken file — it is only in the wrong scope. A string match passes on the defect.
- **#261 and #262 have no in-`src` consumer.** `rg` finds no caller of `parse_specialist_handoff` or
  `reconcile_ensemble` under `src/mergecraft/` — both are library seams the harness has not wired
  yet. The function *is* the observable surface, so the Batch B/C "pin the consumer too" lesson has
  nothing further to reach for on those two; #273 and #263 are where it applied.
- **#273's consumer arms use the private handler builders** (`codex._codex_stream_event_handler`,
  `claude._claude_stream_event_handler`) with `tracer=None`, driven through the real
  `consume_stream`. If W18 renames either builder these two tests need a one-line amendment —
  escalate rather than editing them in an implementation wave.
- **#262's `_finding_key` is imported by the tests.** Key identity is `(path, body)` and the dedup
  assertion depends on it. The tests compare *keys*, not dict identity, so a widened key stays green
  as long as a finding both models reported still keys equal on both sides.

### Reconciled assertions (were 37 xfailed → 36 real passes + 1 rewritten)

All 17 `green after W15|W16|W17|W18|W19` marker decorators (37 parametrized instances) are removed.
Nothing failed once unmarked.

- **W15 (5)** — 4 strip cleanly. The 5th, `test_no_root_key_is_emitted_after_the_first_table`, was
  **defective, not unsatisfied** — rewritten below rather than stripped.
- **W16 (15)** — all five marker casings × three arms are real passes.
- **W17 (4)** — the union arms and the dedup arm are real passes.
- **W18 (7)** — both OpenAI shapes × both accumulator entry points, the cache-write split, and the
  two `codex turn.completed` consumer arms are real passes.
- **W19 (6)** — the validator, the live `ToolContext` path, the tool surface, and the
  `finalize_agent_result` revalidation arm are real passes.

`tests/agents tests/mcp tests/review`: **495 passed / 1 skipped / 6 xfailed / 93 xpassed / 0
failed.** The 6 xfails are the new W18b reds. The 93 XPASS belong to **earlier programs** (`green
after W3` provider-routing, `green after W6` MiniMax routing, …), not to this sweep — they are
outside Batch D's remit and were already XPASS at the W14 baseline.

### The D17 helper was vacuous — the rewrite (escalation, DF)

`_root_keys_after_first_table` collected **every** `key =` line after the first `[header]` with no
notion of table scope, so it also collected keys that legitimately belong to tables (`name`,
`base_url`, `env_key`, `wire_api`, `extends`, `enabled`, the domain entries). `== []` could
therefore only hold for a config whose tables were all empty — unsatisfiable for any correct
output, which is why the test stayed XFAIL after a correct W15 fix.

Two things replace it:

1. **`_keys_by_table_scope(path) -> dict[str, list[str]]`** — tracks the current table header and
   attributes each bare key to it, with the document root as the `""` scope. That makes the
   distinction expressible: `base_url` under `[model_providers.provider_1]` is correct,
   `default_permissions` under it is #222.
2. **The root-key set is derived, not hardcoded.** A render with *no* custom-provider env has no
   table in front of its root keys, so its `""` scope is the writer's intended root set — the arm
   `test_default_permissions_is_already_a_root_key_without_custom_providers` pins that render green
   independently. The test renders twice (no providers, then with providers) and asserts (a) no key
   from the derived root set appears in any table scope, and (b) the derived set is still a subset of
   the provider render's root scope. A root key added to `_append_read_only_mcp_network_lines`
   later is covered with no edit to this test — the property W14 wanted and did not get.

**Evidence it is not passing for the wrong reason.** The rewritten file was run against the
pre-W15 source (a detached worktree at `18311c3` with `PYTHONPATH` pointed at that tree's `src/`,
`--runxfail` so markers do not mask):

```
FAILED test_default_permissions_stays_a_root_key_with_custom_providers[one-indexed-pair]
FAILED test_default_permissions_stays_a_root_key_with_custom_providers[two-indexed-pairs]
FAILED test_default_permissions_stays_a_root_key_with_custom_providers[singleton-alias]
FAILED test_default_permissions_survives_a_partial_provider_pair
FAILED test_no_root_key_is_emitted_after_the_first_table
E  AssertionError: assert ['model_providers.provider_1.default_permissions'] == []
5 failed, 14 passed
```

Against the current source all 11 pass. `test_root_key_scope_helper_flags_the_pre_w15_emission_order`
additionally feeds the tracker a reconstructed pre-W15 TOML fixture and asserts the attribution
directly, so the discriminating behaviour is pinned at the helper level and not only end to end.

### Two coverage gaps the implementation waves reported (added at DF)

- **#261 non-ASCII reasoning.** W16 chose regex-over-original-text precisely because `casefold()` is
  not length-preserving (`ß` → `ss`) and the reasoning half is arbitrary model prose, but **no test
  covered it** — every W14 casing arm used ASCII prose, where `casefold().find()` and the regex
  agree, so a refactor back to the length-sensitive approach would have gone unnoticed.
  `_NON_ASCII_REASONING` puts five expanding characters *before* the marker (a five-byte shift) and
  asserts both halves: the payload parses to one finding and the reasoning carries no marker
  fragment. Confirmed the guard bites — under a `casefold().find()` split all four
  casing × payload combinations raise `JSONDecodeError` and leave `---TY` in the reasoning,
  **including the documented lowercase casing**, which is why the lowercase arm is parametrized in
  too and why `test_lowercase_marker_still_parses` never reached this.
- **#273 second ingress (RED for W18b).** `agents/opencode.py:401-427` — the HTTP session path
  serving the Nous / MiniMax passthrough — re-implements the details-block scan inline and still does
  `input_tokens = inp + cache_read`. New file `tests/agents/test_opencode_session_usage.py`: 6 reds
  marked `xfail(reason="green after W18b: opencode HTTP session cache accounting", strict=False)` and
  6 green guards. **Double-count confirmed live**, not inferred: every red fails
  `assert usage.input_tokens == 100` with `140`. Two properties of this path make it a different
  shape rather than a copy:
  - **Precedence is inverted.** The details block is checked **first**; the Anthropic-native
    `cache_read_input_tokens` / `cacheReadTokens` fields are only a fallback.
    `_resolve_cache_read` consults the native fields first, so a fix that reuses the shared helper
    also flips which field wins on a payload carrying both. `test_anthropic_native_cache_read_stays_additive`
    pins the native-only arm green (it is correct today) so the OpenAI arms cannot be bought by
    deleting the disjoint addition. The ambiguous **both-present** payload was deliberately left
    unpinned — the same call W14 made for the mixed-stream case; pinning it would force W18b to
    choose a resolution rule for a shape no provider emits. **W18b did choose one** — see the
    reconciliation section below, which pins it.
  - **The short `input` / `output` aliases** are accepted here and not by the accumulator, so a fix
    scoped to the long field names would leave the alias inflated; that arm is pinned separately.
  - Both usage container keys (`data["info"]` and `data["usage"]`) are exercised.

### W18b reconciliation — markers stripped, the chosen precedence pinned (DF)

W18b (`99d54f4`) made `_prompt_session_http` **import and reuse** `_resolve_cache_read` from
`agents/_stream_consumer.py` instead of re-deriving the details-block scan inline, so the session
path now computes `input_tokens = inp + (0 if cache_read_is_inclusive else cache_read)`.

- **All 6 W18b reds XPASS; all 6 green guards hold.** The 6
  `green after W18b: opencode HTTP session cache accounting` markers are **stripped**. Nothing failed
  once unmarked, and no assertion was weakened.
- **W18b flipped a precedence this suite had pinned only indirectly.** The pre-W18b inline scan was
  details-first; `_resolve_cache_read` is native-first. Batch D pinned that ordering only *indirectly*
  — via the native-only arm green in both usage containers — and deliberately left the
  **both-present** payload unpinned, so the flip broke no arm and was invisible to the suite. That is
  the gap this reconciliation closes.
- **The chosen rule is now pinned in both directions.**
  `test_both_cache_shapes_resolve_native_first_by_deliberate_choice` asserts the both-present payload
  resolves native-first and **additive** (disjoint) on the session path, across both details keys and
  both usage containers, with the two counts given different values so the assertion identifies
  *which* field won rather than merely that a cached count survived. Its docstring records W18b's
  argument verbatim — reuse over a duplicated rule (the duplicate is what let #273 survive W18 here),
  a delta confined to a shape no real provider emits (the two fields come from mutually exclusive
  APIs), and native-first as the conservative direction for budget accounting, since calling a
  genuinely disjoint count inclusive would under-report prompt size and let a run overrun its bounds.
  The docstring opens with **do not "tidy" this to details-first** so a future reader cannot mistake
  the ordering for an accident.
- **`_stream_consumer` was already pinned** — `test_anthropic_native_field_wins_over_an_openai_details_block`
  has asserted the same native-first/additive contract since W14, so no new test was needed there.
  Both docstrings now cross-reference each other, because the two paths holding *divergent* copies of
  this rule is exactly the bug class that produced W18b.
- **The separation W18b depends on stays pinned.** The native-only and details-only arms are green in
  both usage containers, and the short `input` / `output` alias arms still hold — `_resolve_cache_read`
  never reads the token-count fields, and the alias arms are what keep that true.
- **Out of scope, tracked separately:** `run_bounds.record_agent_usage` adds `cache_read` / `cache_write`
  on top of an `input_tokens` that already contains them, for every provider. Confirmed, distinct from
  #273, and owned by its own wave — no test authored here.

`tests/agents`: **237 passed / 1 skipped / 93 xpassed / 0 failed / 0 xfailed**. `make lint` and
`make typecheck` clean. The 93 XPASS remain the pre-existing `green after W3` / `green after W6`
earlier-program markers, outside Batch D's remit. **No `green after W15`–`W19` or `green after W18b`
marker remains anywhere in `tests/`.**

### Escalation log

| # | Wave that escalated | Test | Finding | Resolution |
|---|---|---|---|---|
| 1 | W15 → DF | `tests/agents/test_codex_custom_provider.py::test_no_root_key_is_emitted_after_the_first_table` | The test, not the fix, was wrong: `_root_keys_after_first_table` ignored table scope, so `== []` was unsatisfiable for any non-empty config and the strongest D17 guard was vacuous | Helper rewritten as `_keys_by_table_scope` with a derived root-key oracle; verified failing against `18311c3` and passing against `3faca32`. A second test pins the helper's attribution against a reconstructed pre-W15 fixture |
| 2 | W16 → DF | `tests/agents/test_structured_handoff.py` | The non-ASCII case W16 hand-verified had no test, so a refactor to `casefold().find()` could regress silently | Two arms added with length-expanding prose before the marker; verified that a `casefold().find()` split fails them |
| 3 | W18 → DF | `tests/agents/test_opencode_session_usage.py` (new) | `agents/opencode.py:401-427` carries the identical #273 double-count on the HTTP session path, outside W18's anchor, so #273's criterion was only half met | 6 RED authored for **W18b** (operator-inserted wave) + 6 green guards; the inverted precedence and the `input`/`output` aliases are pinned so a fix cannot regress the Anthropic arm |
| 4 | W18b → DF | `tests/agents/test_opencode_session_usage.py`, `tests/agents/test_stream_usage_cache.py` | **W18b changed a precedence the suite had pinned only indirectly.** Reusing `_resolve_cache_read` flipped the session path from details-first to native-first. Batch D pinned that ordering only via the native-only arm and left the both-present payload unpinned, so the flip broke no arm — the contract was unpinned in *both* directions and nothing recorded it as a decision | Marker-strip pass plus `test_both_cache_shapes_resolve_native_first_by_deliberate_choice` (2 details keys × `info`/`usage`), whose docstring records W18b's argument and warns against "tidying" it back. `_stream_consumer`'s equivalent pin already existed; both docstrings now cross-reference so the two paths cannot silently diverge again |
