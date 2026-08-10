"""Subprocess boundary for the optional Meat reading-diff lens (#60 spike).

Wave plan: ``.ignorelocal/waves/issues-meat-reading-diff-wave-plan.md``
Worktree: ``mergecraft-meat-a-spike`` @ ``wave/meat-a-spike``

This module is the W2 prototype pinned by the W1 RED suite
(``tests/utils/test_meat_harness.py``). It is a pure boundary: a single
function :func:`run_meat_harness` that takes a unified diff, invokes
``meat -json`` as a subprocess with a bounded timeout, parses the
result, and returns a typed record. The raw diff is **always** retained
on the result (D8). Trust gate, opt-in flag, shell-disabled, and
missing-binary skip are enforced inside the harness (D7, D13) so every
future caller inherits them — they are not the caller's responsibility.

The reading diff is a **lossy** LLM transformation of attacker-controllable
input. It is supplementary context only; the raw diff is the gating
surface (D8, convention 6). The harness itself does not render the
reading diff into a prompt — that is W4's job, gated by the trust tier
and the opt-in flag again at the integration seam.

Design constraints (locked in this plan):

- **D7** — call only when ``trust_tier == "trusted"`` *and*
  ``opt_in is True`` *and* ``shell != "disabled"``. Any missing
  precondition yields a skip with a named ``skip_reason``; the raw
  diff is still returned.
- **D8, convention 6** — :data:`MeatHarnessResult.raw_diff` is the
  input diff, byte-for-byte, on every code path. The reading diff is
  never a replacement.
- **D11** — ``-json`` is the wire format. Never scrape the coloured
  terminal output.
- **D13** — a missing binary is a skip with an install hint, never a
  failure.
- **convention 5** — every unit test drives the harness through a fake
  subprocess under ``tmp_path``. The harness does not import any
  HTTP client and never resolves ``shutil.which("meat")`` itself; the
  caller passes the binary path (the caller is expected to know whether
  it has it via the prep module).
- **convention 8** — credentials are referenced by env-var name only
  (the runtime env is the caller's responsibility); the harness never
  logs or stores the value. The subprocess inherits the process env, so
  the credential reaches ``meat`` through ``os.environ`` — the harness
  only adds safe extras (the timeout, the cache hint) and never reads
  ``OPENAI_API_KEY`` / ``ANTHROPIC_API_KEY`` itself.

``run_meat_harness`` is intentionally the only public entry point. The
result dataclass is slotted and frozen so it can be reused on the
return path of W4's integration without mutation.

Exports:
    MeatHarnessResult — dataclass holding the result.
    run_meat_harness — the only public entry point.

Examples:
    >>> from pathlib import Path
    >>> from mergecraft.utils.meat_harness import run_meat_harness
    >>> diff = "diff --git a/x b/x\\n--- a/x\\n+++ b/x\\n@@ -1 +1 @@\\n-old\\n+new\\n"
    >>> result = run_meat_harness(
    ...     raw_diff=diff,
    ...     meat_binary=Path("/nonexistent"),
    ...     trust_tier="trusted",
    ...     opt_in=True,
    ...     shell="restricted",
    ...     timeout_seconds=1.0,
    ... )
    >>> result.raw_diff == diff
    True
    >>> result.abridged_diff is None
    True
    >>> result.skip_reason is not None
    True
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

from loguru import logger

#: Wire format keys Meat emits on ``-json`` (D11). Snake-case, stable
#: across the pinned upstream version. ``elision`` is optional and
#: appears when Meat chooses to drop a hunk; the harness surfaces it
#: as a non-blocking signal on the result.
_MEAT_RESULT_KEYS: frozenset[str] = frozenset(
    {"smart_diff", "summary", "input_tokens", "output_tokens", "elision"}
)

#: Minimum required keys for a parse to be considered successful.
#: ``smart_diff`` and ``summary`` are mandatory; the token counters are
#: optional so older Meat builds still parse.
_MEAT_REQUIRED_KEYS: frozenset[str] = frozenset({"smart_diff", "summary"})

#: Env-var names the harness promises it never reads or logs (convention 8).
#: They are present so a static check can assert the harness does not
#: ``os.environ.get(name)`` them directly.
MEAT_CREDENTIAL_ENV_VARS: frozenset[str] = frozenset({"OPENAI_API_KEY", "ANTHROPIC_API_KEY"})

#: Env-var names whose **values** are stripped from subprocess stderr tails
#: before they are surfaced in a log record, stored on
#: :attr:`MeatHarnessResult.skip_reason`, or printed by an operator tool.
#: The harness does not read these vars itself; the redaction is a
#: defence-in-depth against a misconfigured upstream that reflects a
#: credential value in an error message.
_MEAT_REDACT_ENVVARS: tuple[str, ...] = (
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "MEAT_MODEL",
)

#: Shell values that the harness treats as "shell disabled" (D7).
#: ``disabled`` is the explicit kill-switch; anything else (``restricted``,
#: ``enabled``, ``repo-native``, ...) is left to the caller's policy
#: layer. The integration point in W4 narrows this further.
SHELL_DISABLED_VALUES: frozenset[str] = frozenset({"disabled"})


def _redact_env_values(text: str) -> str:
    """Strip the values of ``_MEAT_REDACT_ENVVARS`` from ``text`` (convention 8).

    Subprocess stderr is third-party-controlled. If a misconfigured
    upstream (or a future version of Meat) ever reflects a credential
    value in an error message, that value must not land in a log record,
    on :attr:`MeatHarnessResult.skip_reason`, or in any operator-printed
    output. The harness does not have access to the actual values — the
    caller passes the diff and binary path; the env reaches the
    subprocess via process inheritance. When the value is not visible to
    the harness, ``os.environ.get`` is the natural source — that is what
    a misconfigured upstream error would also reach.

    Returns ``text`` unchanged when no credential env-var is set in the
    process. When one is set, the literal value is replaced with
    ``<REDACTED:NAME>`` so the diagnostic context is preserved.
    """
    out = text
    for name in _MEAT_REDACT_ENVVARS:
        value = os.environ.get(name)
        if value:
            out = out.replace(value, f"<REDACTED:{name}>")
    return out


@dataclass(slots=True, frozen=True)
class MeatHarnessResult:
    """Typed result of one Meat invocation.

    Fields:

    - ``raw_diff`` — the input diff, byte-for-byte, on every code path
      (D8). Even when abridgement ran, returned, and was perfect, the
      raw diff is here; the reading diff is supplementary.
    - ``abridged_diff`` — Meat's ``smart_diff`` payload on success;
      ``None`` on any failure or skip.
    - ``summary`` — Meat's one-line summary on success; ``None`` on any
      failure or skip.
    - ``skip_reason`` — a named reason when abridgement was skipped
      (D13: missing binary, D7: gate tripped, timeout, malformed JSON,
      non-zero exit). ``None`` when abridgement ran successfully.
    - ``input_tokens`` — Meat's reported input tokens on success;
      ``None`` otherwise.
    - ``output_tokens`` — Meat's reported output tokens on success;
      ``None`` otherwise.
    - ``elision`` — Meat's narrative string on ``-json`` when it
      records dropping a hunk; ``None`` otherwise. Non-blocking signal.
    - ``executed`` — ``True`` when the subprocess was actually invoked.
      Useful for telemetry — distinguishes "gate tripped" from
      "subprocess failed".
    """

    raw_diff: str
    abridged_diff: str | None = None
    summary: str | None = None
    skip_reason: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    elision: str | None = None
    executed: bool = False


def _skip_result(raw_diff: str, reason: str, *, executed: bool = False) -> MeatHarnessResult:
    """Build a skip result with the raw diff retained verbatim.

    Single source of truth for the skip shape — every failure branch
    funnels through this so D8 (raw diff always retained) cannot drift.
    """
    return MeatHarnessResult(
        raw_diff=raw_diff,
        abridged_diff=None,
        summary=None,
        skip_reason=reason,
        input_tokens=None,
        output_tokens=None,
        elision=None,
        executed=executed,
    )


def _parse_meat_json(payload: str, raw_diff: str) -> MeatHarnessResult:
    """Parse a ``-json`` payload into a typed result.

    Any parse failure (invalid JSON, missing required keys, non-string
    ``smart_diff`` / ``summary``) raises :class:`ValueError`. The caller
    catches that and degrades to the raw diff with a named skip reason.
    """
    data: Any = json.loads(payload)
    if not isinstance(data, dict):
        msg = f"meat -json top-level value is not an object: {type(data).__name__}"
        raise ValueError(msg)
    missing = _MEAT_REQUIRED_KEYS - data.keys()
    if missing:
        msg = f"meat -json payload missing required keys: {sorted(missing)}"
        raise ValueError(msg)
    smart_diff = data["smart_diff"]
    summary = data["summary"]
    if not isinstance(smart_diff, str) or not isinstance(summary, str):
        msg = "meat -json 'smart_diff' / 'summary' must be strings"
        raise ValueError(msg)
    input_tokens = data.get("input_tokens")
    output_tokens = data.get("output_tokens")
    if input_tokens is not None and not isinstance(input_tokens, int):
        msg = (
            f"meat -json 'input_tokens' must be int when present, got {type(input_tokens).__name__}"
        )
        raise ValueError(msg)
    if output_tokens is not None and not isinstance(output_tokens, int):
        msg = f"meat -json 'output_tokens' must be int when present, got {type(output_tokens).__name__}"
        raise ValueError(msg)
    elision = data.get("elision")
    if elision is not None and not isinstance(elision, str):
        msg = f"meat -json 'elision' must be string when present, got {type(elision).__name__}"
        raise ValueError(msg)
    return MeatHarnessResult(
        raw_diff=raw_diff,
        abridged_diff=smart_diff,
        summary=summary,
        skip_reason=None,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        elision=elision,
        executed=True,
    )


def run_meat_harness(
    *,
    raw_diff: str,
    meat_binary: Path,
    trust_tier: str,
    opt_in: bool,
    shell: str,
    timeout_seconds: float,
) -> MeatHarnessResult:
    """Invoke the Meat reading-diff harness with a bounded timeout.

    Args:
        raw_diff: the unified diff to abridge. Retained verbatim on the
            result regardless of what happens downstream (D8).
        meat_binary: absolute path to the ``meat`` executable. The
            caller resolves it (typically via the prep module) so the
            harness itself never touches ``shutil.which`` and the unit
            tests can swap a fake binary under ``tmp_path``.
        trust_tier: "trusted" or "untrusted". Anything other than
            "trusted" is treated as untrusted (D7) — the gate is
            closed by default.
        opt_in: explicit consumer opt-in flag. Default-off (convention 7).
        shell: shell-policy value. ``"disabled"`` (and any value in
            :data:`SHELL_DISABLED_VALUES`) closes the gate (D7).
        timeout_seconds: hard ceiling on the subprocess wall-clock. A
            hung ``meat`` is killed at this point and the result
            degrades to the raw diff with a "timeout" skip reason.

    Returns:
        A :class:`MeatHarnessResult`. Its ``raw_diff`` field always
        equals the input ``raw_diff`` byte-for-byte. ``abridged_diff``,
        ``summary``, ``input_tokens``, ``output_tokens`` are populated
        only on a successful parse; any failure or skip leaves them
        ``None`` and populates ``skip_reason`` with a human-readable
        explanation.
    """
    # Trust gate, opt-in, and shell-disabled are enforced here so every
    # future caller inherits them. Order is stable for log stability.
    if trust_tier != "trusted":
        return _skip_result(
            raw_diff,
            "skip: trust tier is not 'trusted' (D7 gate tripped)",
        )
    if not opt_in:
        return _skip_result(
            raw_diff,
            "skip: meat reading-diff is opt-in and the flag is unset (convention 7)",
        )
    if shell in SHELL_DISABLED_VALUES:
        return _skip_result(
            raw_diff,
            "skip: shell is disabled; abridgement would require new shell execution (D7)",
        )

    # Missing binary is a skip with an install hint — D13, never a failure.
    if not meat_binary.exists():
        logger.warning(
            "meat binary not found at {}; skipping reading-diff lens "
            "(install via `go install meat.dev/cmd/meat@latest`).",
            meat_binary,
        )
        return _skip_result(
            raw_diff,
            "skip: meat binary not found; install via `go install meat.dev/cmd/meat@latest`",
        )

    # The subprocess inherits the *process* env unchanged. The harness
    # explicitly does NOT read OPENAI_API_KEY / ANTHROPIC_API_KEY /
    # MEAT_MODEL — they are the caller's surface (convention 8). The
    # subprocess both reads the diff from stdin and writes the JSON
    # result to stdout (D11).
    try:
        completed = subprocess.run(
            [str(meat_binary), "-json"],
            input=raw_diff,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired:
        logger.warning(
            "meat -json timed out after {}s; skipping reading-diff lens.",
            timeout_seconds,
        )
        return _skip_result(
            raw_diff,
            f"skip: meat timed out after {timeout_seconds}s",
            executed=True,
        )
    except OSError as exc:
        logger.warning(
            "meat -json could not be executed: {}; skipping reading-diff lens.",
            exc,
        )
        return _skip_result(
            raw_diff,
            f"skip: meat could not be executed ({exc})",
        )

    if completed.returncode != 0:
        stderr_tail = (completed.stderr or "").strip().splitlines()
        tail = stderr_tail[-1] if stderr_tail else ""
        tail_redacted = _redact_env_values(tail or "no stderr")
        logger.warning(
            "meat -json exited non-zero ({}): {}; skipping reading-diff lens.",
            completed.returncode,
            tail_redacted,
        )
        return _skip_result(
            raw_diff,
            f"skip: meat exited {completed.returncode}: {tail_redacted}",
            executed=True,
        )

    try:
        return _parse_meat_json(completed.stdout, raw_diff)
    except ValueError as exc:
        # The exception message originates inside the harness's own
        # parser; it does not carry subprocess stderr, but we still pass
        # it through the redactor so a future parser change that surfaces
        # subprocess text does not silently introduce a leak.
        msg_redacted = _redact_env_values(str(exc))
        logger.warning(
            "meat -json output was malformed ({}); skipping reading-diff lens.",
            msg_redacted,
        )
        return _skip_result(
            raw_diff,
            f"skip: meat -json output malformed: {msg_redacted}",
            executed=True,
        )
