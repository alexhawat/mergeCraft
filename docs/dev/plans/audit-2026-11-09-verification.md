# Verification of the 2026-11-09 security and quality audit

Audited commit: `5dbaa2d4` (`main`, also the base of this branch). The source audit is the
"mergeCraft — full security and quality audit" report of 9 November 2026, which lists 44
findings (6 high, 16 medium, 19 low, 2 nit, 1 info). This memo verifies each finding
against the source at that commit, and re-rates severity where the evidence calls for it.
Source was not changed.

## Method

- Read every cited location at `5dbaa2d4`, and followed callers and mitigations outside
  the cited lines.
- Ran offline probes on Python 3.14.6 with the locked environment (`uv sync --frozen`):
  - seeded redaction sampling: 200 tokens per length;
  - an `httpx.MockTransport` tracing round-trip through `MemorySink`;
  - Jev state filtering;
  - the sandbox failure classifier;
  - layered config loading with malformed YAML and duplicate keys;
  - `git_argv` patch-flag hardening;
  - asyncio and `Popen` reaping;
  - ruff 0.15.12 and 0.16.7 run with `--select ALL`.
- The full unit suite, type checks and dependency scan were **not** re-run. The audit's
  test and scan matrix is reported as-is, unverified.

Verdicts:

- **Confirmed**: the defect exists as described.
- **Confirmed, corrected**: the defect exists, but a material detail was wrong (cause,
  reachability, or scope).
- **Rejected**: the claimed defect does not occur.

## Summary

| Severity | Audit | After verification |
| --- | --- | --- |
| High | 6 | 1 |
| Medium | 16 | 13 |
| Low | 19 | 26 |
| Nit | 2 | 2 |
| Info | 1 | 1 |
| Rejected | 0 | 1 |

43 of 44 findings reproduce. One is rejected (F30). The audit is accurate on mechanism,
but it overstates exploitability for most of its "high" findings. Five of the six
highs are real code defects with no current path to the impact the audit describes, or
with mitigations it missed.

F1 is the exception, and it is worse than reported. The free-text redactor leaks about
40% of random tokens at **every** length, not only at 80 characters and above. The
cause is a camelCase identifier exemption that the audit did not identify.

## Verdict table

| ID | Audit | Verdict | Revised | Key reason |
| --- | --- | --- | --- | --- |
| F1 | High | Confirmed, corrected | **High** | Leaks at every length via camelCase exemption; `sk-ant-` and `sk-proj-` are caught |
| F12 | High | Confirmed, corrected | Medium | Mechanism real; no production path raises a URL-bearing error inside `send` |
| F13 | High | Confirmed, corrected | Low | All 7 pack ids used in code are registered; latent only |
| F14 | High | Confirmed, corrected | Medium | Untrusted analyzers pre-scrub; fork runs with credentials are refused |
| F15 | High | Confirmed, corrected | Medium | Real fail-open, but surfaced as a skip and not PR-triggerable |
| F16 | High | Confirmed, corrected | Low | Needs a transient probe failure; any hang is bounded by the analyzer timeout |
| F2 | Medium | Confirmed | Medium | Only `same-repo` or `None` can be returned |
| F3 | Medium | Confirmed, corrected | Medium | Manifest pins ruff 0.15.12, not 0.16.7; both emit only `error` |
| F4 | Medium | Confirmed | Medium | All 4 harness startup shapes classify as `None` |
| F17 | Medium | Confirmed | Medium | No new session or process-group kill on timeout |
| F18 | Medium | Confirmed | Medium | `(allow file-read*)` with no privilege drop on Darwin |
| F19 | Medium | Confirmed | Medium | Only the refspec source is checked |
| F20 | Medium | Confirmed | Medium | Shell half fails closed (functional); push has no floor |
| F21 | Medium | Confirmed | Low | Metrics only; the fix needs a new `stale` outcome kind |
| F22 | Medium | Confirmed, corrected | Low | Tool payloads are already byte-capped upstream |
| F23 | Medium | Confirmed | Medium | Hash ignores the `MERGECRAFT_CONFIG` source |
| F24 | Medium | Confirmed, corrected | Low | It is `uv pip`, which has its own HTTP timeouts |
| F25 | Medium | Confirmed, corrected | Low | Token is operator-supplied with charset `[A-Za-z0-9_]`; no injector |
| F26 | Medium | Confirmed | Medium | Blocking subprocess calls inside async handlers |
| F27 | Medium | Confirmed | Low | Oversized-diff reduction and a summary only; files with spaces |
| F28 | Medium | Confirmed | Medium | Readers mutate the bound issue number; progress writes use it |
| F29 | Medium | Confirmed | Low | Advisory evidence; arguably deliberate all-or-nothing |
| F5 | Low | Confirmed, corrected | Low | Partial: depends on the shape of path segments |
| F6 | Low | Confirmed | Low | Malformed YAML widens `disabled` to `restricted` |
| F30 | Low | **Rejected** | n/a | asyncio's child watcher reaps the killed process |
| F31 | Low | Confirmed, corrected | Low | Early returns also skip restoration (broader) |
| F32 | Low | Confirmed | Low | No timeout; `rmdir` raises on a non-empty directory |
| F33 | Low | Confirmed | Low | No timeout on local git calls |
| F34 | Low | Confirmed | Low | PATH fallback skips lock and hash verification |
| F35 | Low | Confirmed | Low | Unguarded row indexing |
| F36 | Low | Confirmed | Low | No workspace confinement on `diff_path` |
| F37 | Low | Confirmed | Low | `repo` is declared in 6 schemas and never read |
| F7 | Low | Confirmed, corrected | Low | Reachable: the agent git tool allows `log -u` |
| F8 | Low | Confirmed | Low | Last duplicate key wins, silently |
| F38 | Low | Confirmed | Low | Non-atomic write on the comment-preserving path |
| F39 | Low | Confirmed, corrected | Low | Relative `..` paths also escape (broader) |
| F40 | Low | Confirmed | Low | `mkstemp` file descriptor leaked |
| F41 | Low | Confirmed | Low | Temp directory leaked; mount has no timeout |
| F42 | Low | Confirmed | Low | `chown`, `chmod` and `is_dir` follow symlinks |
| F43 | Low | Confirmed, corrected | Low | Zombies are reaped by the next `Popen`, not held until exit |
| F44 | Low | Confirmed | Low | Bare sink does not redact; factory path does |
| F9 | Nit | Confirmed | Nit | Unreachable latin-1 decode handler |
| F10 | Nit | Confirmed, corrected | Nit | Lint counts reproduce; typo sub-claim is weak |
| F11 | Info | Partially confirmed | Info | Spot-checked only |

## High findings

### F1 — free-text redaction leaks long and lowercase-leading tokens (stays High)

Confirmed at `src/mergecraft/analyzers/redact.py`, and the measured exposure is wider
than reported. The probe embedded tokens in a sentence and ran them through
`redact_secrets`, 200 seeded base-62 tokens per length.

| Length | Leak rate, all tokens | Leak rate, uppercase or digit first character |
| --- | --- | --- |
| 24 | 39.0% | 0.0% |
| 32 | 35.5% | 0.0% |
| 48 | 49.0% | 0.0% |
| 63 | 36.0% | 0.0% |
| 64 | 53.5% | 17.7% |
| 80 | 83.5% | 74.8% |
| 90 | 97.0% | 93.9% |
| 120 | 100.0% | 100.0% |

There are two independent causes. The audit found only the second.

1. **Missed by the audit: the camelCase exemption.** `_BENIGN_IDENTIFIER_RE` contains
   the alternative `[a-z][a-z0-9]*(?:[A-Z][a-z0-9]*)+`. It matches **any** alphanumeric
   token that starts with a lowercase letter and contains an uppercase letter. That
   covers about 42% of random base-62 strings. The exemption runs before the dense-token
   rule in `_entropy_redact`, `_maybe_redact_entire_string` and
   `_is_benign_entropy_token`, so these tokens survive at any length. For example,
   `Bearer k3UIG6VT…` (40 characters) leaked in the probe.
2. **Found by the audit: the length-relative threshold.** The threshold is
   `0.85 * log2(len)`, and `_should_force_redact_dense_token` returns early at
   `len >= 64`. Together they let long tokens through even when the first character is
   uppercase.

Corrections to the audit's pattern list:

- `sk-ant-…` and `sk-proj-…` **are** redacted: the existing `\bsk-[A-Za-z0-9_-]{8,}`
  pattern matches them.
- A 26-character `glpat-` token was redacted by the dense-token rule.
- Confirmed leaks: `github_pat_` (93 characters), `pypi-` (170 characters), and
  `Bearer` followed by a lowercase-leading value.

**Fix:**

- Restrict the camelCase alternative to identifier-like shapes. For example, require at
  least two lowercase letters between capitals, or cap the digit ratio. Or move the
  dense-token check ahead of it.
- Add `github_pat_`, `pypi-` and `Bearer` patterns.
- Replace the length-relative threshold with an absolute per-character cut.
- Drop the length-64 exemption.

### F12 — URL userinfo in span error text (High → Medium)

The mechanism is confirmed:

- `Span.record_exception` stores `str(exc)` as `error`.
- The span closes with `attrs.setdefault("error", …)`.
- `redact_attrs` applies `redact_secrets`, which has no userinfo rule.

The probe leaked `alice:hunter2pw@` through `MemorySink` in two cases: an event-hook
`raise_for_status()`, and a transport error whose message embeds the URL. The `api_key`
query value was redacted, as the audit says.

Reachability is narrower than claimed:

- Only `agents/lite.py` and `agents/opencode.py` instrument clients.
- No client in `src/` registers event hooks.
- The opencode base URL is the local `opencode serve` endpoint.
- No production path raises an exception inside `send` whose message carries a userinfo
  URL.

This is a defense-in-depth gap. **Fix as proposed:** run `redact_url` over the error
text, or apply it in `redact_attrs` for the `error` key.

### F13 — unknown Jev pack fails open (High → Low)

The behaviour is confirmed. `filter_state_for_pack` returns `dict(state)` unfenced when
`state_fields_for` is empty, and the probe returned `password` and `token` for
`nope/v9`.

It is latent, though. The only caller is `jev/client.py:330`, and every pack id passed
in code is one of the seven `*_PACK_ID` constants. All seven are registered in
`PACK_REGISTRY`, so no current input reaches the open branch. **Fix as proposed**, as
hardening: treat an unknown pack as allow-nothing.

### F14 — `envAllowlist` overrides the sensitive-name deny list (High → Medium)

Confirmed in `utils/secrets.py`. In `filter_env`, `user_allowed` bypasses
`is_sensitive_env_name`. Two paths have no always-strip step:

- the restricted MCP shell: `mcp/shell.py:445` calls `resolve_env("restricted")`, which
  calls `filter_env()`;
- trusted-tier analyzers: `build_analyzer_env` and `run.py`'s
  `plan.env or filter_env()` fallback.

The audit missed two mitigations:

- Untrusted-tier `build_analyzer_env` drops sensitive names, `GITHUB_TOKEN` and
  `GH_TOKEN` **before** calling `filter_env`. The allowlist cannot re-admit them there,
  so "analyzers" in general are not exposed.
- `action/inputs.py` refuses fork pull-request runs when provider credentials are
  present. A fork-authored `envAllowlist` therefore cannot reach an agent-driven
  restricted shell. Same-repo authors already have write access.

There is also a related gap the audit did not mention. `_user_allowlist` is
process-global, and `clear_env_allowlist` is only called from tests. **Fix as
proposed:** apply the always-strip set inside `filter_env`, and read the allowlist from
the base snapshot.

### F15 — one bad TruffleHog line drops the scan (High → Medium)

Confirmed. `parsers/trufflehog_jsonl.py:76` calls `json.loads` with no guard, while the
mypy, buf and `_common` parsers do guard. The adapter turns the error into
`skipped=True, findings=[]`.

The impact is smaller than described:

- The skip is reported with a `skip_reason`, so it is not silent.
- TruffleHog in `-j` mode writes logs to stderr.
- PR file content is JSON-escaped inside findings, so a PR author cannot inject a raw
  line.

**Fix as proposed:** skip the bad line instead of dropping the scan.

### F16 — process-limit probe fallback lacks headroom (High → Low)

Confirmed. When `_drop_exec_succeeds_at_limit` returns `None` mid-loop (timeout or
`OSError`), the fallback is `count + allowance`, without the extra allowance the success
path adds.

The trigger needs all of the following: running as root, `setpriv` present, a transient
probe failure, and an under-reported `/proc` count. The outcome is then either an EAGAIN
failure or a hang that the analyzer timeout bounds (TruffleHog's is 180 s). It is not
indefinite. **Fix as proposed.**

## Medium findings

- **F2 (Medium, confirmed).** `_minimal_granting_tier` iterates
  `reversed(_TIER_LOOSEN_ORDER)`. `same-repo` natively honours every non-fork event, so
  only `same-repo` or `None` can come back. The result feeds the Codex remedy text in
  `agents/codex.py:651-654`. Tests only stub `granting_tier` and never call the
  function.
- **F3 (Medium, confirmed, corrected).** `ruff.yaml` maps `error` to `Major`. Ruff
  0.15.12 (the manifest pin; the runtime is repo-native) and 0.16.7 (the dev
  dependency) were both run with `--select ALL`. Both emitted only `severity: "error"`.
  The audit cited 0.16.7 as the pinned version; the manifest pins 0.15.12.
- **F4 (Medium, confirmed).** `classify_sandbox_failure` returns `None` for all four
  harness startup shapes:
  - unshare, operation not permitted;
  - unshare fork, resource temporarily unavailable;
  - bwrap namespace creation;
  - uid_map write.
- **F17 (Medium, confirmed).** `analyzers/run.py` calls `subprocess.run(timeout=…)`
  without `start_new_session`. On `TimeoutExpired`, only the direct child is killed.
- **F18 (Medium, confirmed).** `sandbox_exec_policy` has `(allow file-read*)`. The
  `sandbox-exec` branch of `_spawn_shell` skips the git binds, the binary masks and the
  socket nulling, and on Darwin there is no privilege drop. The Linux path has no read
  allowlist either, but it drops to the agent uid.
- **F19 (Medium, confirmed).** `git_fetch_tool` runs `reject_special_ref` on
  `refspec.split(":")[0]` only. The destination is forwarded unchanged, under
  `ToolClass.REPOSITORY_READ`.
- **F20 (Medium, confirmed).** None of the event dicts that `resolve_native_event` builds
  carries `authorPermission`. As a result, `_stricter_shell` always downgrades `enabled`
  to `restricted` on the native path. That half fails closed, so it is a functional
  bug. The security-relevant half is push: `payload.py:723` resolves
  `inputs.push or settings.push or "restricted"` with no collaborator floor.
- **F23 (Medium, confirmed).** `config_yaml_hash` covers only the committed file and the
  local overlay. `layered.py` makes `MERGECRAFT_CONFIG` the sole source when it is set,
  and `assert_config_unchanged` returns early when the baseline is empty.
- **F26 (Medium, confirmed).** The shell and git tools are `async def _run` handlers that
  call blocking `communicate` and `subprocess.run(timeout=600)` directly.
  `mcp/shared.execute` does not offload them. The post-timeout
  `communicate(timeout=5)` sits outside the exception handler.
- **F28 (Medium, confirmed).** `issue_events.py:19` and `issue_comments.py:18` overwrite
  `primary_repo_state(...).issue_number`. `comment.py:200` uses that value for progress
  writes, and `verdict.py:1372` falls back to it when `pr_number` is unset.

## Medium findings re-rated to Low

- **F21.** Confirmed: `isOutdated` maps to `fixed`, and no test passes
  `outdated=True`. The impact is on metrics only. `FindingOutcomeKind` has no `stale`
  member, so the fix must add one.
- **F22.** Confirmed: the cap counts characters in top-level string values only.
  However, `redact_tool_payload` already caps tool input and output at 64 KiB of UTF-8
  bytes, which removes the main risk the audit names.
- **F24.** Confirmed: no timeout, and the call holds the provision lock. The command is
  `uv pip install`, which applies its own per-request HTTP timeout
  (`UV_HTTP_TIMEOUT`).
- **F25.** Confirmed: raw interpolation into `echo "{token}"`. The token is the
  operator's GitHub token, whose charset is `[A-Za-z0-9_]`, and nothing
  attacker-controlled reaches it. This is hardening only.
- **F27.** Confirmed: `split()[3]` turns `a/my file.txt` into `file.txt`. It affects
  oversized-diff reduction and a summary, and only for files with spaces. The second
  site is `utils/offline_diff.py`, not `offline_diff.py`.
  `analyzers/scope.split_diff_git_paths` exists and can replace both.
- **F29.** Confirmed: the early return drops attestations already collected. The
  evidence is advisory, and all-or-nothing may be intentional.

## Low, nit and info findings

### Rejected

- **F30.** The main claim, that the timed-out setup script is "killed but never reaped",
  does not hold. The process comes from `asyncio.create_subprocess_shell`, and asyncio's
  child watcher reaps it. In the probe, `killpg` without `wait` left no `/proc` entry,
  and `returncode` was `-9`. A minor sub-point stands: `kill_process_group` calls
  `time.sleep(0.2)` synchronously when invoked from async code.

### Confirmed, with corrections

- **F5.** Partial: `/home/runner/work/repo/src/app/module.py` is redacted, but
  `/tmp/x/a.py` and some other absolute paths survive the benign-stem rule.
- **F7.** The flag gap is confirmed: `git_argv(["log", "-u"])` injects neither
  `--no-ext-diff` nor `--no-textconv`. The audit's "no current caller passes `-u`" is
  wrong, because the agent-facing MCP git tool allows the `log` short flags `cmpuz`
  (`mcp/git_guards.py:160`). Impact stays low, since an external diff or textconv needs
  git config or an env var that a PR cannot set.
- **F31.** Broader than reported. Besides an exception from settings loading, the early
  `return _stamp_jev_skip(...)` before the `try` at line 1185 also skips restoration.
- **F39.** Broader than reported. A relative `../..` joined onto `GITHUB_WORKSPACE` is
  not confined either.
- **F43.** The zombie is real (probe state `Z`). CPython puts unreaped `Popen` objects
  in `subprocess._active` and reaps them on the next `Popen`, so they do not persist
  until the server exits.

### Confirmed as described

- **F6.** `shell: disabled` with a syntax error loads as `restricted`. Only
  `config validate` passes `strict=True`.
- **F8.** Duplicate `shell:` keys silently keep the last value, in both directions.
- **F32.** `worktree add` and `remove` have no timeout. On failure, `rmdir` raises if
  the directory is not empty.
- **F33.** `rev-parse` and `show` run without a timeout.
- **F34.** `resolve_baked_binary` falls back to `shutil.which`. `execution.py:197` and
  `impact.py:375` then skip `resolve_with_lock`.
- **F35.** `int(m["range"]["start"]["line"])` is unguarded.
- **F36.** `validate_review_scope_evidence` reads any readable path. Error messages do
  not echo its content.
- **F37.** `"repo"` appears in six schemas and is never read.
- **F38.** The comment-preserving branch uses `path.write_text`.
- **F40.** The file descriptor from `mkstemp(...)[1]` is discarded.
- **F41.** The `mkdtemp` directory is never removed, and `mount --bind` has no timeout.
- **F42.** `is_dir`, `chown` and `chmod(0o755)` all follow symlinks.
- **F44.** `JSONLFileSink.write` dumps `model_dump()` without redaction.

### Nit and info

- **F9 (Nit, confirmed).** `decode("latin-1")` cannot raise, so its handler is dead
  code.
- **F10 (Nit, confirmed, corrected).** Ruff 0.16.7 on `docs/dev/plans` reports 18 errors
  (PT018 ×9, T201 ×5, I001 ×4), and 7 docs files fail `format --check`. Only
  `audit-2026-11-05-security-probes.py` imports a removed symbol
  (`evidence_producers._require_workflow_untouched`). The typo sub-claim is weak:
  "unparseable" is an accepted spelling, and the "iz" hit is inside a regex.
- **F11 (Info, partial).** Spot-checked only. `clear_env_allowlist` is used by tests, so
  it is not dead. See F14 for why its absence from production matters.

## Corrections to the audit's posture section

- "No … shell invocation anywhere in the source" is inaccurate. `main.py:1692` runs
  `settings.setup_script` through `asyncio.create_subprocess_shell`. That is restricted
  to the trusted tier and is by design. The MCP shell tool also executes `bash -c`.
- The other posture claims were not individually re-verified.

## Revised fix order

1. **F1:** the camelCase exemption, the missing prefixes, the absolute entropy cut, and
   dropping the length-64 exemption.
2. **F14, F15, F12:** always-strip inside `filter_env`; tolerate bad lines in the
   TruffleHog parser; run `redact_url` on span error text.
3. **F19, F18, F20 (push floor), F2:** git refspec destination, the macOS read scope,
   the collaborator floor for push, and tier recommendation order.
4. **F4, F3, F17, F26:** classify sandbox startup as cannot-run; map ruff severity by
   rule class; kill process groups; move blocking MCP work off the event loop.
5. **F23, F28:** hash the config that was actually loaded; make the bound issue number
   immutable.
6. **F13, F16, F7, F6, F8:** latent fail-open edges. Make unknown packs allow nothing,
   add fork headroom, add the `-u` flag, fail closed on malformed YAML, reject duplicate
   keys.
7. **Remaining items:** timeouts, reaping, atomic writes, confinement, descriptor and
   temp-directory leaks, and the stale probe scripts.
