"""Execute analyzer plans and capture outcomes."""

from __future__ import annotations

import contextlib
import os
import re
import subprocess
import sys
import tempfile
import threading
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from loguru import logger

from mergecraft.analyzers._resource_limits import resource_limited_argv
from mergecraft.analyzers.redact import redact_analyzer_output, redact_secrets
from mergecraft.errors import ConfigurationError
from mergecraft.utils.process_group import kill_process_group, track_process_group
from mergecraft.utils.process_scope import check_process_cancelled
from mergecraft.utils.secrets import filter_env

if TYPE_CHECKING:
    from typing import IO

    from mergecraft.analyzers.resolve import AnalyzerPlan
    from mergecraft.analyzers.sandbox import SandboxContext

CHECK_TIMEOUT_S = 300
MAX_OUTPUT_CHARS = 8_000
# Per-stream ceiling on captured analyzer output that is redacted and parsed.
# Enforced while the pipe is read (the reader keeps only the head and discards
# the rest), so a chatty analyzer cannot grow the parent's memory.
MAX_CAPTURED_OUTPUT_CHARS = 32 * 1024 * 1024
# Read size for one pipe chunk, and the bound on joining a reader whose stream
# never reaches EOF because a process outside the killed group still holds it.
_CAPTURE_READ_CHARS = 64 * 1024
_READER_JOIN_TIMEOUT_S = 5.0

_SANDBOX_BOOTSTRAP_ENV = {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C", "LC_ALL": "C"}
_RESTORE_PAYLOAD_ENV = """set -eu
readonly _MERGECRAFT_BOOTSTRAP_FD="$MERGECRAFT_PAYLOAD_ENV_FD"
unset MERGECRAFT_PAYLOAD_ENV_FD
while IFS= read -r -d '' _MERGECRAFT_BOOTSTRAP_ENTRY; do
    export "$_MERGECRAFT_BOOTSTRAP_ENTRY"
done <&"$_MERGECRAFT_BOOTSTRAP_FD"
case "$_MERGECRAFT_BOOTSTRAP_FD" in ''|*[!0-9]*) exit 2 ;; esac
eval "exec ${_MERGECRAFT_BOOTSTRAP_FD}<&-"
exec "$@"
"""


CheckStatus = Literal[
    "passed",
    "failed",
    "timed_out",
    "unavailable",
    "declared-but-cannot-run",
    # #36: the gate did not run *here*, but the consumer's CI ran an
    # equivalent one and it passed. Only reachable through an explicitly
    # declared gate → check-run mapping (D10); never inferred from a name.
    "satisfied-by-ci",
]

# Statuses that mean "this environment produced no verdict about the diff".
_NO_VERDICT: frozenset[str] = frozenset({"unavailable", "declared-but-cannot-run"})

PASSING_CHECK_STATUSES: frozenset[str] = frozenset({"passed", "satisfied-by-ci"})
"""The single answer to "does this gate row count as passing?".

Every consumer imports this rather than spelling its own set. It lives beside
``CheckStatus`` because that Literal is the closed vocabulary it partitions,
so a new status cannot be added without deciding here whether it passes.

Two readers disagreed before this existed: ``AnalyzerOutcome.passed`` accepted
``satisfied-by-ci`` while the approval gate's own allowlist did not, so a repo
whose ``ciEvidence`` proved a gate green had its terminal approve rejected.
If a new status is added to ``CheckStatus``, decide here whether it passes and
both readers follow.
"""

REQUIRED_CHECK_SATISFIED_STATUSES: frozenset[str] = PASSING_CHECK_STATUSES | {"not_applicable"}
"""Statuses that satisfy a *required* gate (AG0-G4a / MCB-16).

Derived from ``PASSING_CHECK_STATUSES``, never spelled independently, so the
two questions cannot drift: "was this gate proved green?" and "does this row
satisfy a required gate?" differ only by ``not_applicable`` — a gate that does
not apply to this diff satisfies the requirement without ever having passed.

``not_applicable`` is absent from ``CheckStatus`` and no producer emits it
today; it is kept because the required-gate contract is pinned on it
(``tests/agents/test_required_static_checks.py``) and a consumer-declared gate
is the obvious future source.
"""


@dataclass(frozen=True, slots=True)
class AnalyzerOutcome:
    """Result of running one analyzer or static gate."""

    name: str
    command: str
    status: CheckStatus
    output: str
    exit_code: int | None = None
    output_path: str | None = None

    @property
    def passed(self) -> bool:
        """True when the gate is proved green — here, or by declared CI evidence."""
        return self.status in PASSING_CHECK_STATUSES

    @property
    def ran(self) -> bool:
        return self.status not in _NO_VERDICT


def _run_tmpdir(plan: AnalyzerPlan, *, output_dir: Path | None = None) -> Path:
    """Return the directory gate output is persisted to.

    A sandboxed run passes ``output_dir`` — the sandbox/run tmpdir — so the
    persisted output never lands in the real checkout. The unsandboxed path
    persists under the per-process analyzer run root, also outside the checkout,
    so no host-side write goes through a path the reviewed tree supplies.
    """
    _ = plan
    if output_dir is not None:
        tmpdir = output_dir
    else:
        from mergecraft.analyzers.sandbox import analyzer_run_root

        tmpdir = analyzer_run_root() / "analyzer-runs"
    tmpdir.mkdir(parents=True, exist_ok=True)
    return tmpdir


def _persist_output(
    redacted: str, *, plan: AnalyzerPlan, output_dir: Path | None = None
) -> str | None:
    """Persist already-redacted parser input; the caller redacts each stream once."""
    if not redacted:
        return None
    from mergecraft.analyzers.parse import persist_analyzer_output

    path = persist_analyzer_output(
        redacted, tmpdir=_run_tmpdir(plan, output_dir=output_dir), tool_id=plan.manifest_id
    )
    return str(path)


def _cap_captured(text: str) -> tuple[str, bool]:
    """Keep the head of one captured stream (parsers need its start); flag a cut."""
    if len(text) <= MAX_CAPTURED_OUTPUT_CHARS:
        return text, False
    return text[:MAX_CAPTURED_OUTPUT_CHARS], True


# Characters a credential-shaped token (or URL userinfo) is made of. A cut at any
# other character cannot split one, so nothing redaction would catch whole is
# left behind as a prefix.
_TOKEN_CHARS = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-+/=.~:@%")
_TOKEN_BOUNDARY_SCAN_CHARS = 4096


def _redaction_safe_head(text: str) -> str:
    """Return the head of a cut stream, cut where no value straddles the cut.

    Applies to an over-cap stream and to a stream the reader truncated: the cut
    lands after the last complete line inside the limit, or, when the head is one
    long line (minified JSON), just before the last character that cannot belong
    to a token. Either way the kept text stays within the limit, and a quoted
    value the head opens but does not close is dropped as well.
    """
    limit = min(MAX_CAPTURED_OUTPUT_CHARS, len(text))
    newline = text.rfind("\n", 0, limit)
    if newline >= limit // 2:
        return _drop_open_quoted_value(text[:newline])
    for index in range(limit - 1, max(limit - _TOKEN_BOUNDARY_SCAN_CHARS, 0) - 1, -1):
        if text[index] not in _TOKEN_CHARS:
            return _drop_open_quoted_value(text[:index])
    return _drop_open_quoted_value(text[:limit])


def _last_unescaped(text: str, quote: str) -> int:
    index = text.rfind(quote)
    while index > 0 and text[index - 1] == "\\":
        index = text.rfind(quote, 0, index)
    return index


def _opens_value(text: str, quote_index: int) -> bool:
    """Whether the quote at *quote_index* directly follows ``:`` or ``=`` (spaces allowed)."""
    before = quote_index - 1
    while before >= 0 and text[before].isspace():
        before -= 1
    return before >= 0 and text[before] in ":="


def _drop_open_quoted_value(head: str) -> str:
    """Cut *head* before a quoted value it opens (``key: "`` / ``key='``) but never closes.

    The redactor's assignment rules match a quoted value only up to its closing
    quote, so a value the cut left open would otherwise be kept as written. A
    quote is taken as opening a value when it is the last unescaped quote of its
    kind and directly follows ``:`` or ``=``.
    """
    for _ in range(4):
        cut = len(head)
        for quote in ('"', "'"):
            index = _last_unescaped(head, quote)
            if index >= 0 and _opens_value(head, index):
                cut = min(cut, index)
        if cut == len(head):
            break
        head = head[:cut]
    return head


def _redact_stream(text: str, *, plan: AnalyzerPlan) -> str:
    return redact_analyzer_output(text, tool_id=plan.manifest_id) if text else text


def _redact_captured(text: str, *, plan: AnalyzerPlan, truncated: bool = False) -> tuple[str, bool]:
    """Redact one captured stream, keeping at most the cap; flag a cut.

    Redaction has to see whole credentials: a cut at an arbitrary offset can
    leave a token's prefix below every rule's minimum length, and that prefix
    survives redaction. An over-cap stream -- and a stream the reader truncated
    at the cap -- is cut on a safe boundary first, so the redactor sees no
    straddling value and its work stays bounded by the cap. The result is capped
    again only after redaction, where a cut can no longer expose anything.
    """
    cut = truncated or len(text) > MAX_CAPTURED_OUTPUT_CHARS
    head = _redaction_safe_head(text) if cut else text
    redacted, recut = _cap_captured(_redact_stream(head.strip(), plan=plan))
    return redacted, cut or recut


@dataclass(frozen=True, slots=True)
class _SandboxLimits:
    """Resolved limits and sandbox context for the isolated child launcher.

    The process cap is calibrated in the parent before launch because its
    credential-changing probe must run outside the limited child.
    """

    context: SandboxContext
    process_limit: tuple[int, int]


def _truncate(text: str, *, output_path: str | None = None) -> str:
    if len(text) <= MAX_OUTPUT_CHARS:
        return text
    if output_path:
        elided = len(text) - MAX_OUTPUT_CHARS
        return (
            f"... [{elided} chars truncated; full output saved to {output_path}] ...\n"
            f"{text[-MAX_OUTPUT_CHARS:]}"
        )
    return text[:MAX_OUTPUT_CHARS] + f"\n… truncated at {MAX_OUTPUT_CHARS} chars"


def _command_string(argv: tuple[str, ...]) -> str:
    import shlex

    return shlex.join(argv)


def _trusted_identity_drop(
    plan: AnalyzerPlan, sandbox_context: SandboxContext | None
) -> tuple[AnalyzerPlan, str | None]:
    """Drop a trusted-tier catalog payload to the agent UID (#878).

    Applies only to a catalog analyzer on the root backend: it carries a
    ``SandboxContext`` that is *not* a read-only (untrusted) one. Static gates pass
    no context and build their own drop prefix; untrusted payloads drop inside the
    namespace script. Returns ``(plan_to_run, refusal)``; a refusal is a named
    reason and the caller must not run the payload — an analyzer that cannot be
    dropped never runs as root.

    The scratch tree is re-owned to the drop target *before* the payload starts,
    otherwise ``jscpd`` and the pattern scanners cannot write it and exit
    ``failed``, which reads as a finding about the diff.
    """
    if (
        sandbox_context is None
        or sandbox_context.read_only_source
        or sys.platform == "win32"
        or os.geteuid() != 0
    ):
        return plan, None
    from mergecraft.analyzers import sandbox as sandbox_mod
    from mergecraft.utils.privilege import _path_owned_by_uid

    try:
        drop = sandbox_mod.build_privilege_drop_argv()
    except ConfigurationError as exc:
        return plan, f"identity drop unavailable, analyzer not run as root: {exc}"
    if not drop:
        return plan, None
    uid = sandbox_mod.resolve_drop_target_uid()
    gid = sandbox_mod.resolve_drop_target_gid()
    if uid is None or gid is None:
        return plan, "identity drop unavailable, analyzer not run as root: no drop target"
    scratch = sandbox_context.scratch_dir
    run_root = sandbox_mod.analyzer_run_root()
    boundary = run_root if run_root in scratch.parents else sandbox_context.repo_root
    try:
        sandbox_mod.hand_tree_to_drop_target(scratch, boundary=boundary, uid=uid, gid=gid)
    except OSError as exc:
        return plan, f"analyzer scratch cannot be handed to the agent user: {exc}"
    env = dict(plan.env or filter_env())
    if not _path_owned_by_uid(env.get("HOME", ""), uid):
        env["HOME"] = str(scratch)
    return replace(plan, argv=(*drop, *plan.argv), env=env), None


def _early_unavailable_outcome(plan: AnalyzerPlan) -> AnalyzerOutcome | None:
    """Short-circuit outcomes that never touch a subprocess (skip / not-yet-runnable mode)."""
    if plan.mode == "skip":
        return AnalyzerOutcome(
            name=plan.manifest_id,
            command="",
            status="unavailable",
            output=plan.reason or f"skipped {plan.manifest_id}",
        )
    if plan.mode in {"ci-result", "managed", "container"} and not plan.argv:
        return AnalyzerOutcome(
            name=plan.manifest_id,
            command="",
            status="unavailable",
            output=f"{plan.mode} execution is not available in this wave",
        )
    return None


def _sandboxed_argv(
    plan: AnalyzerPlan,
    sandbox_context: SandboxContext | None,
    *,
    event_name: str = "",
    event: dict[str, Any] | None = None,
    self_review_level: str = "off",
    analyzer_id: str = "",
    netns_name: str | None = None,
    egress_session: Any | None = None,
) -> tuple[list[str], _SandboxLimits | None]:
    """Wrap ``plan.argv`` in namespace isolation when the sandbox context requires it.

    The untrusted (read-only source) context is always wrapped. A trusted context
    is wrapped too whenever filtered egress applies (``egress_session`` or
    ``netns_name`` given): the filter and the resource limits are part of the
    egress decision, so they hold on every tier the policy reaches.
    """
    run_argv = list(plan.argv)
    if sandbox_context is None or not _requires_wrapping(
        sandbox_context, egress_session=egress_session, netns_name=netns_name
    ):
        return run_argv, None
    if sys.platform == "win32":
        from mergecraft.analyzers.egress import FilteredEgressSetupError

        raise FilteredEgressSetupError("untrusted analyzer requires a Linux namespace backend")
    from mergecraft.analyzers.sandbox import (
        build_analyzer_sandbox_argv_for_run,
        process_limit_for_drop,
        resolve_drop_target_gid,
        resolve_drop_target_uid,
    )

    # The drop target's ``RLIMIT_NPROC`` pair is resolved here, in the parent:
    # the child launcher must not probe while under its own resource limits. A
    # credential-changing ``execve`` is refused ``EAGAIN`` when the target uid
    # already exceeds ``RLIMIT_NPROC`` (SX-D2). ``process_limit_for_drop`` probes
    # the kernel for a limit that carries the drop, so it must run outside the
    # limited child.
    preexec_fn = _SandboxLimits(
        sandbox_context,
        process_limit=process_limit_for_drop(
            sandbox_context.max_processes,
            target_uid=resolve_drop_target_uid(),
            target_gid=resolve_drop_target_gid(),
        ),
    )
    event_payload = event if event is not None else {}
    # Repository-provided PATH/loader/shell variables only reach the payload
    # after namespace setup and capability removal. They cannot choose helpers.
    payload_argv = (
        "/bin/bash",
        "--noprofile",
        "--norc",
        "-c",
        _RESTORE_PAYLOAD_ENV,
        "mergecraft-analyzer",
        *plan.argv,
    )
    return (
        build_analyzer_sandbox_argv_for_run(
            payload_argv,
            context=sandbox_context,
            event_name=event_name,
            event=event_payload,
            self_review_level=self_review_level,
            analyzer_id=analyzer_id or plan.manifest_id,
            netns_name=netns_name,
            egress_session=egress_session,
        ),
        preexec_fn,
    )


def _requires_wrapping(
    sandbox_context: SandboxContext,
    *,
    egress_session: Any | None = None,
    netns_name: str | None = None,
) -> bool:
    """Whether this run goes through the namespace wrapper and its limits."""
    return sandbox_context.read_only_source or egress_session is not None or netns_name is not None


class _CapturedProcess(subprocess.CompletedProcess[str]):
    """A completed run that also records which streams a reader had to cut."""

    def __init__(
        self,
        args: str | list[str],
        returncode: int,
        stdout: str | None,
        stderr: str | None,
        *,
        truncated: frozenset[str],
    ) -> None:
        super().__init__(args, returncode, stdout, stderr)
        self.truncated = truncated


class _StreamReader:
    """One pipe's bounded reader: its retained text and whether bytes were dropped."""

    def __init__(self, name: str, stream: IO[str] | None) -> None:
        self.name = name
        self.text = ""
        self.truncated = False
        self._stream = stream
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._stream is None:
            return
        self._thread = threading.Thread(
            target=self._drain, name=f"analyzer-{self.name}", daemon=True
        )
        self._thread.start()

    def _drain(self) -> None:
        if self._stream is not None:
            self.text, self.truncated = _read_bounded_stream(
                self._stream, MAX_CAPTURED_OUTPUT_CHARS
            )

    @property
    def alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def join(self) -> None:
        """Wait (bounded) for this reader; a reader that outlives the wait dropped output."""
        if self._thread is None:
            return
        self._thread.join(timeout=_READER_JOIN_TIMEOUT_S)
        if self._thread.is_alive():
            self.truncated = True

    def close(self) -> None:
        """Close the pipe, unless a reader is still blocked on it."""
        if self.alive or self._stream is None:
            return
        with contextlib.suppress(OSError, ValueError):
            self._stream.close()


def _read_bounded_stream(stream: IO[str], cap: int) -> tuple[str, bool]:
    """Read one pipe to EOF, keeping at most ``cap`` bytes and discarding the rest.

    The cap counts UTF-8 bytes, so a multi-byte stream may retain fewer than
    ``cap`` characters. Reading continues after the cap so the child never blocks
    on a full pipe. Returns the retained text and whether bytes were dropped; a
    read that ends before EOF (the parent closed the pipe after a bounded join)
    or on undecodable bytes is a dropped tail, not a complete stream.
    """
    kept: list[str] = []
    retained = 0
    truncated = False
    try:
        while True:
            chunk = stream.read(_CAPTURE_READ_CHARS)
            if not chunk:
                break
            if truncated:
                continue
            encoded = chunk.encode("utf-8", "replace")
            if retained + len(encoded) <= cap:
                kept.append(chunk)
                retained += len(encoded)
                continue
            truncated = True
            remaining = cap - retained
            if remaining > 0:
                kept.append(encoded[:remaining].decode("utf-8", "ignore"))
    except UnicodeDecodeError:
        # ``text=True`` decodes strictly: undecodable bytes end this stream, and
        # the outcome must say output was dropped rather than report a clean pass.
        return "".join(kept), True
    except (OSError, ValueError):
        # The parent closed the pipe after the bounded join, so the tail was
        # dropped: report a cut, never a complete stream.
        return "".join(kept), True
    return "".join(kept), truncated


def _run_in_own_session(
    run_argv: list[str],
    *,
    cwd: Path | None,
    timeout_s: int,
    env: dict[str, str],
    pass_fds: tuple[int, ...],
    preexec_fn: _SandboxLimits | None,
) -> _CapturedProcess:
    """``subprocess.run`` that heads its own session and reaps the whole group.

    ``subprocess.run`` kills only the direct child on timeout, so a grandchild
    (a language server, a watcher, a forked test runner) outlives the analyzer
    and keeps the stdout/stderr pipes -- and the runner -- busy. Start the child
    as a session leader before the resource-limit launcher and namespace
    privilege drop, and ``killpg`` the group on timeout.

    Both pipes are drained by one reader thread each, which keeps at most
    ``MAX_CAPTURED_OUTPUT_CHARS`` bytes and keeps reading past the cap so the
    child never blocks on a full pipe. The run is finished only when the child
    has exited **and** both pipes reached EOF: a grandchild still holding a pipe
    keeps the output incomplete, which is reported as a timeout and takes the
    group down, exactly as ``communicate()`` treated it.
    """
    if isinstance(preexec_fn, _SandboxLimits):
        # A Python callback between fork and exec can inherit locked interpreter
        # state from another analyzer worker. Apply limits after a fresh exec.
        run_argv = resource_limited_argv(
            run_argv,
            process_limit=preexec_fn.process_limit,
            memory_mb=preexec_fn.context.memory_mb,
        )
    check_process_cancelled()
    proc = subprocess.Popen(
        run_argv,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
        pass_fds=pass_fds,
        start_new_session=True,
    )
    readers = [
        _StreamReader("stdout", proc.stdout),
        _StreamReader("stderr", proc.stderr),
    ]
    with contextlib.ExitStack() as scope:
        try:
            scope.enter_context(track_process_group(proc))
            for reader in readers:
                reader.start()
            proc.wait(timeout=timeout_s)
            # EOF, not just the child's exit: a grandchild that inherited a pipe
            # never finished writing, which is the timeout ``communicate()`` saw.
            for reader in readers:
                reader.join()
            if any(reader.alive for reader in readers):
                raise subprocess.TimeoutExpired(run_argv, timeout_s)
            check_process_cancelled()
        except BaseException:
            # TimeoutExpired, KeyboardInterrupt, ...: take the whole tree down.
            kill_process_group(proc.pid)
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                with contextlib.suppress(OSError):
                    proc.kill()
                with contextlib.suppress(subprocess.TimeoutExpired):
                    proc.wait(timeout=1)
            for reader in readers:
                reader.join()
            raise
        finally:
            # Never close a pipe a reader is still blocked on: ``close()`` waits
            # for that thread's lock, and the writer may never let go. A daemon
            # reader left blocked here dies with the parent.
            for reader in readers:
                reader.close()
    return _CapturedProcess(
        run_argv,
        proc.returncode,
        readers[0].text,
        readers[1].text,
        truncated=frozenset(reader.name for reader in readers if reader.truncated),
    )


def _run_subprocess(
    run_argv: list[str],
    *,
    plan: AnalyzerPlan,
    cwd: Path | None,
    timeout_s: int,
    preexec_fn: _SandboxLimits | None,
    command: str,
    sandboxed: bool = False,
) -> _CapturedProcess | AnalyzerOutcome:
    """Run the analyzer subprocess; a caught timeout/OSError becomes a terminal outcome."""
    try:
        with contextlib.ExitStack() as resources:
            # SX-D5: an empty/None plan.env must resolve to the default-deny
            # filter, never to ``None`` (which inherits ``os.environ``) or to a
            # raw copy of the orchestrator's environment.
            environment = plan.env or filter_env()
            pass_fds: tuple[int, ...] = ()
            if sandboxed:
                payload_env = plan.env or filter_env()
                if os.geteuid() == 0 and isinstance(preexec_fn, _SandboxLimits):
                    # SX2: a payload dropped to the agent user cannot write the
                    # runner-owned HOME it inherited; point it at the writable
                    # scratch tmpfs instead, or every cache write fails (P-8).
                    payload_env = {
                        **payload_env,
                        "HOME": str(preexec_fn.context.scratch_dir),
                    }
                if any(
                    not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key)
                    or key.startswith("_MERGECRAFT_BOOTSTRAP_")
                    or key == "MERGECRAFT_PAYLOAD_ENV_FD"
                    or "\0" in value
                    for key, value in payload_env.items()
                ):
                    return AnalyzerOutcome(
                        name=plan.manifest_id,
                        command=command,
                        status="unavailable",
                        output="invalid analyzer payload environment",
                    )
                # Unlinked private file: values never enter argv, shell source,
                # logs, or the privileged bootstrap environment.
                payload_file = resources.enter_context(tempfile.TemporaryFile())
                payload_file.write(
                    b"".join(f"{key}={value}\0".encode() for key, value in payload_env.items())
                )
                payload_file.seek(0)
                descriptor = payload_file.fileno()
                pass_fds = (descriptor,)
                environment = {
                    **_SANDBOX_BOOTSTRAP_ENV,
                    "MERGECRAFT_PAYLOAD_ENV_FD": str(descriptor),
                }
            return _run_in_own_session(
                run_argv,
                cwd=cwd,
                timeout_s=timeout_s,
                env=environment,
                pass_fds=pass_fds,
                preexec_fn=preexec_fn,
            )
    except subprocess.TimeoutExpired:
        logger.warning("analyzer {} timed out after {}s", plan.manifest_id, timeout_s)
        return AnalyzerOutcome(
            name=plan.manifest_id,
            command=command,
            status="timed_out",
            output=f"timed out after {timeout_s}s",
        )
    except OSError as exc:
        logger.info("analyzer {} is unavailable: {}", plan.manifest_id, exc)
        return AnalyzerOutcome(
            name=plan.manifest_id,
            command=command,
            status="unavailable",
            output=f"not installed in this environment: {exc}",
        )


def _outcome_from_completed(
    completed: subprocess.CompletedProcess[str],
    *,
    plan: AnalyzerPlan,
    command: str,
    output_dir: Path | None = None,
    truncated: frozenset[str] = frozenset(),
) -> AnalyzerOutcome:
    """Combine stdout/stderr, redact, persist to disk, and build the final outcome.

    Each stream is redacted exactly once, on input already bounded by the capture
    layer (:func:`_read_bounded_stream`). A stream whose reader dropped bytes is
    cut on a redaction-safe boundary and reported with the exceeded notice, even
    when the retained text is under the character cap.
    """
    stdout, stdout_cut = _redact_captured(
        completed.stdout or "", plan=plan, truncated="stdout" in truncated
    )
    stderr, stderr_cut = _redact_captured(
        completed.stderr or "", plan=plan, truncated="stderr" in truncated
    )
    for_parser = stdout or stderr
    combined = for_parser
    if stderr and stdout:
        combined = f"{stdout}\n{stderr}".strip()
    elif stderr:
        combined = stderr
    if plan.version_note:
        combined = f"{redact_secrets(plan.version_note)}\n{combined}".strip()
    # Persist only what a parser can read. ``combined`` is the display string and
    # may be nothing but ``plan.version_note`` prose when the analyzer wrote to
    # neither stream; persisting that turned a clean run into "failed to parse".
    output_path = _persist_output(for_parser, plan=plan, output_dir=output_dir)
    display = _truncate(combined, output_path=output_path)
    if stdout_cut or stderr_cut:
        display = (
            f"analyzer output exceeded {MAX_CAPTURED_OUTPUT_CHARS} chars per stream; "
            f"the rest was dropped before parsing\n{display}"
        )
    return AnalyzerOutcome(
        name=plan.manifest_id,
        command=command,
        status="passed" if completed.returncode == 0 else "failed",
        output=display,
        exit_code=completed.returncode,
        output_path=output_path,
    )


def run_plan(
    plan: AnalyzerPlan,
    *,
    sandbox_context: SandboxContext | None = None,
    event_name: str = "",
    event: dict[str, Any] | None = None,
    self_review_level: str = "off",
    analyzer_id: str = "",
) -> AnalyzerOutcome:
    """Run one resolved plan. Never raises."""
    from mergecraft.utils.payload import read_github_event

    resolved_event_name = event_name or os.environ.get("GITHUB_EVENT_NAME", "")
    resolved_event = event if event is not None else read_github_event()
    early = _early_unavailable_outcome(plan)
    if early is not None:
        return early

    cwd = plan.cwd
    timeout_s = plan.timeout_s or CHECK_TIMEOUT_S
    if sandbox_context is not None:
        timeout_s = min(timeout_s, sandbox_context.timeout_s)
    command = _command_string(plan.argv)
    from mergecraft.analyzers.egress import (
        EgressSession,
        FilteredEgressSetupError,
        start_filtered_egress_session,
    )

    session: EgressSession | None = None
    # A trusted run with no GitHub event is a local CLI run: its egress is the
    # operator's own (the same rule ``analyzer_egress_skip_reason`` applies).
    local_trusted = (
        sandbox_context is not None
        and not sandbox_context.read_only_source
        and resolved_event is None
    )
    if sandbox_context is not None and not local_trusted:
        from mergecraft.analyzers.sandbox import evaluate_analyzer_egress_policy

        event_payload = resolved_event if resolved_event is not None else {}
        outcome = evaluate_analyzer_egress_policy(
            analyzer_id=analyzer_id or plan.manifest_id,
            network_allowlist=list(sandbox_context.network_allowlist),
            event_name=resolved_event_name,
            event=event_payload,
            self_review_level=self_review_level,
        )
        if outcome.status == "skipped":
            # Fail closed: an allowlist the policy cannot filter never falls
            # through to host networking, whatever the execution tier.
            logger.info("{}", outcome.reason)
            return AnalyzerOutcome(
                name=plan.manifest_id,
                command=command,
                status="unavailable",
                output=outcome.reason,
            )
        if outcome.status == "filtered":
            try:
                session = start_filtered_egress_session(list(sandbox_context.network_allowlist))
            except FilteredEgressSetupError as exc:
                reason = (
                    f"Skipped: egress policy — {plan.manifest_id} declares network hosts "
                    f"but filtered egress could not be applied ({exc})"
                )
                logger.info("{}", reason)
                return AnalyzerOutcome(
                    name=plan.manifest_id,
                    command=command,
                    status="unavailable",
                    output=reason,
                )
    wrapped = sandbox_context is not None and _requires_wrapping(
        sandbox_context, egress_session=session
    )
    # F2-b: a wrapped run's output is persisted into the sandbox/run tmpdir; an
    # unwrapped run's into the per-process run root. Neither is in the checkout.
    output_dir: Path | None = None
    if sandbox_context is not None and wrapped:
        output_dir = sandbox_context.scratch_dir / "analyzer-runs"
    plan_to_run = plan
    if not wrapped:
        # A wrapped payload drops identity inside the namespace script; only an
        # unwrapped trusted payload takes the identity-drop prefix here.
        plan_to_run, drop_refusal = _trusted_identity_drop(plan, sandbox_context)
        if drop_refusal is not None:
            logger.info("analyzer {}: {}", plan.manifest_id, drop_refusal)
            if session is not None:  # pragma: no cover - session implies wrapped
                session.close()
            return AnalyzerOutcome(
                name=plan.manifest_id, command=command, status="unavailable", output=drop_refusal
            )
    try:
        run_argv, preexec_fn = _sandboxed_argv(
            plan_to_run,
            sandbox_context,
            event_name=resolved_event_name,
            event=resolved_event,
            self_review_level=self_review_level,
            analyzer_id=analyzer_id or plan.manifest_id,
            egress_session=session,
        )
        result = _run_subprocess(
            run_argv,
            plan=plan_to_run,
            cwd=cwd,
            timeout_s=timeout_s,
            preexec_fn=preexec_fn,
            command=command,
            sandboxed=output_dir is not None,
        )
        if isinstance(result, AnalyzerOutcome):
            return result
        return _outcome_from_completed(
            result,
            plan=plan,
            command=command,
            output_dir=output_dir,
            truncated=result.truncated,
        )
    except FilteredEgressSetupError as exc:
        return AnalyzerOutcome(
            name=plan.manifest_id,
            command=command,
            status="unavailable",
            output=f"sandbox isolation unavailable: {exc}",
        )
    finally:
        if session is not None:
            session.close()


def run_version_probe(
    argv: list[str], *, timeout_s: int = 10
) -> subprocess.CompletedProcess[str] | None:
    """Run a trusted-tier tool ``--version`` probe through the analyzer spawn path.

    The probe gets what a trusted analyzer payload gets: the scrubbed analyzer
    environment (never the orchestrator's own), its own process group reaped on
    timeout, a neutral empty working directory, and on a root orchestrator the
    same identity drop — a probe that cannot be dropped is not run. Returns
    ``None`` instead of raising when the probe cannot run or times out.
    """
    from mergecraft.analyzers.trust import build_analyzer_env

    prefix: list[str] = []
    if sys.platform != "win32" and os.geteuid() == 0:
        from mergecraft.analyzers.sandbox import build_privilege_drop_argv

        try:
            prefix = build_privilege_drop_argv()
        except ConfigurationError as exc:
            logger.info(
                "version probe for {} not run: identity drop unavailable ({})", argv[0], exc
            )
            return None
    try:
        with tempfile.TemporaryDirectory(prefix="mergecraft-probe-") as workdir:
            return _run_in_own_session(
                [*prefix, *argv],
                cwd=Path(workdir),
                timeout_s=timeout_s,
                env=build_analyzer_env(tier="trusted"),
                pass_fds=(),
                preexec_fn=None,
            )
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        logger.info("version probe for {} did not complete: {}", argv[0], exc)
        return None


def run_plans(
    plans: list[AnalyzerPlan],
    *,
    sandbox_context: SandboxContext | None = None,
) -> list[AnalyzerOutcome]:
    return [run_plan(plan, sandbox_context=sandbox_context) for plan in plans]


__all__ = [
    "CHECK_TIMEOUT_S",
    "MAX_OUTPUT_CHARS",
    "AnalyzerOutcome",
    "CheckStatus",
    "run_plan",
    "run_plans",
    "run_version_probe",
]
