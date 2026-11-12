"""Normalize raw CI failures to a stable, redacted shape (K1.4 / K1.5)."""

from __future__ import annotations

import hashlib
import re
from typing import Any, cast

from mergecraft.analyzers.redact import redact_for_fingerprint, redact_secrets
from mergecraft.ci.paths import extract_failure_paths
from mergecraft.ci.types import NormalizedFailure, RawFailure

_TIMESTAMP_PREFIX = re.compile(r"^\d{4}-\d{2}-\d{2}T[\d:.]+Z\s*")
_RUN_ID_TOKEN = re.compile(r"\b\d{10,}\b")
_ERROR_LINE = re.compile(
    r"(##\[error\][^\n]*|AssertionError[^\n]*|Error[^\n]*|FAIL(?:ED)?[^\n]*|"
    r"make: \*\*\*[^\n]*|Process completed with exit code [1-9]\d*)",
    re.I,
)

# Lines every failing step prints regardless of cause. A signature built from
# one would give unrelated failures the same fingerprint (#1321).
_GENERIC_LINE = re.compile(
    r"^(?:##\[error\]\s*|Error:\s*)?(?:"
    r"Process completed with exit code \d+\.?"
    r"|make(?:\[\d+\])?: \*\*\* .*Error \d+"
    r"|Found \d+ errors?\b.*"
    r")$",
    re.I,
)
_STRUCTURAL_LINE = re.compile(r"^##\[(?:group|endgroup)\]", re.I)
# ``path:line[:col]:`` positions shift when unrelated lines move; the
# diagnostic identity is the path and the message.
_POSITION = re.compile(r"(\S):\d+(?::\d+)?:")


def _strip_run_noise(text: str) -> str:
    lines = []
    for line in text.splitlines():
        cleaned = _TIMESTAMP_PREFIX.sub("", line)
        cleaned = _RUN_ID_TOKEN.sub("<run-id>", cleaned)
        lines.append(cleaned.strip())
    return "\n".join(line for line in lines if line)


def _extract_error_signature(raw: RawFailure, log_excerpt: str) -> tuple[str, bool]:
    """Return ``(signature, specific)`` for one failure excerpt.

    ``specific`` is False when the excerpt holds nothing but lines every failing
    step prints (GitHub's exit-code trailer, ``make: ***``, "Found N errors").
    """
    explicit = raw.get("error_signature")
    if explicit:
        return _strip_run_noise(str(explicit)), True
    lines = [line for line in _strip_run_noise(log_excerpt).splitlines() if line]
    for line in lines:
        if _GENERIC_LINE.match(line):
            continue
        match = _ERROR_LINE.search(line)
        if match:
            return match.group(0), True
    # No specific error line (ruff, flake8, eslint, shellcheck, custom scripts):
    # use the last diagnostic printed before the first generic summary line.
    first_generic = next(
        (index for index, line in enumerate(lines) if _GENERIC_LINE.match(line)), len(lines)
    )
    for line in (*reversed(lines[:first_generic]), *reversed(lines[first_generic:])):
        if not _GENERIC_LINE.match(line) and not _STRUCTURAL_LINE.match(line):
            return _POSITION.sub(r"\1:", line), True
    return (lines[-1] if lines else "unknown failure"), False


def _compute_fingerprint(
    *, job: str, step: str, command: str, error_signature: str, specific: bool
) -> str:
    """Hash the command and error signature (#1321).

    A specific diagnostic identifies the root cause on its own, so the same
    defect in several jobs still clusters. A generic-only signature does not:
    the job and step are hashed too, so unrelated jobs never share an identity.
    """
    parts = (command, error_signature) if specific else (job, step, command, error_signature)
    material = redact_for_fingerprint("\0".join(part.strip() for part in parts), tool_id="ci")
    return hashlib.sha256(material.encode()).hexdigest()[:16]


def _coerce_exit_code(raw: RawFailure) -> int:
    value = raw.get("exit_code")
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return 1


def _coerce_artifacts(raw: RawFailure) -> list[str]:
    artifacts = raw.get("artifacts") or []
    if not isinstance(artifacts, list):
        return []
    return [redact_secrets(str(path)) for path in artifacts]


def normalize_failure(raw: dict[str, Any]) -> NormalizedFailure:
    """Normalize a raw provider failure to the K1.4 field table with ingest redaction."""
    typed = cast(  # raw is dict[str, Any]; cast to TypedDict for typed field access
        "RawFailure", raw
    )
    job = str(raw.get("job_name") or raw.get("job") or "unknown")
    step = str(raw.get("step_name") or raw.get("step") or "unknown")
    command = redact_secrets(str(raw.get("command") or ""))
    exit_code = _coerce_exit_code(typed)

    source_excerpt = str(raw.get("log_excerpt") or raw.get("log_text") or "")
    stripped_excerpt = _strip_run_noise(source_excerpt)
    failure_paths = extract_failure_paths(stripped_excerpt)
    log_excerpt = redact_secrets(stripped_excerpt)
    error_signature, specific = _extract_error_signature(typed, log_excerpt)
    artifacts = _coerce_artifacts(typed)
    retry_state = raw.get("retry_state")
    if retry_state is not None:
        retry_state = str(retry_state)

    return NormalizedFailure(
        job=job,
        step=step,
        command=command,
        exit_code=exit_code,
        log_excerpt=log_excerpt,
        artifacts=artifacts,
        retry_state=retry_state,
        failure_fingerprint=_compute_fingerprint(
            job=job,
            step=step,
            command=command,
            error_signature=error_signature,
            specific=specific,
        ),
        failure_paths=failure_paths,
    )


__all__ = ["normalize_failure"]
