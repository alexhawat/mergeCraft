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
| B — Action / workflow contract (#264, #265, #272, #271) | W6 | _append below_ | pending |
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
