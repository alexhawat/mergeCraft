"""Sandbox-caused gate failure signatures (SX-D7).

An untrusted static check runs inside the untrusted sandbox: network off, a
scrubbed environment, and the checkout presented as a disposable copy-on-write
view. A gate that fails *because of the sandbox* produced no verdict about the
diff, so reporting it as ``failed`` invents a code defect (P-8). This module is
the single table that names those failures by the stderr they carry, and the
classifier the gate runner uses to turn them into ``declared-but-cannot-run``.

Two reasons, spelled exactly once:

* :data:`NETWORK_DISABLED_REASON` — the gate could not reach the network
  (package download, registry lookup).
* :data:`PATH_NOT_WRITABLE_REASON` — the gate tried to write outside the scratch
  view and the kernel refused.

A signature matches only *sandbox* shapes. Ordinary tool output that happens to
mention ``network`` in a message about the user's code is left unclassified, so
a real lint failure is still the gate's result.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

NETWORK_DISABLED_REASON = "sandboxed: network is disabled"
PATH_NOT_WRITABLE_REASON = "sandboxed: path not writable"

# Network shapes. A DNS failure, an unreachable network, or a name-resolution
# error is the sandbox's ``--net`` with no route. ``connection refused`` is
# handled separately: it is only a sandbox signature when the refused target is
# not loopback (a loopback refusal is the gate's own local server failing).
_NETWORK_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"temporary failure in name resolution", re.IGNORECASE),
    re.compile(r"could not resolve host", re.IGNORECASE),
    re.compile(r"network is unreachable", re.IGNORECASE),
    re.compile(r"\bENETUNREACH\b"),
    re.compile(r"\bEHOSTUNREACH\b"),
    re.compile(r"\bgetaddrinfo\b", re.IGNORECASE),
    re.compile(r"\bEAI_AGAIN\b"),
)

_CONNECTION_REFUSED_RE = re.compile(r"connection refused", re.IGNORECASE)

# Write-denied shapes. ``EROFS`` / "read-only file system" name the read-only
# bind; ``EACCES`` is the permission the sandboxed identity lacks outside its
# scratch view. These are errno-level tokens a tool prints for a kernel denial,
# so they match on their own. The human-readable spelling coreutils print for
# the same denial is ``Permission denied`` (and, for the same class of syscall,
# ``Operation not permitted``) — but by the time a gate's output reaches this
# classifier the redaction boundary has already replaced the denied path with
# ``<redacted>``, so the path can no longer be the signal. Match on the *write
# operation* named on the same line instead: the shape a real denied
# ``mkdir``/``cp``/``open``/``touch`` takes, and a shape ordinary *code* output
# (a lint error about a policy, a message about the user's own code) does not.
_WRITE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bEROFS\b"),
    re.compile(r"read-only file system", re.IGNORECASE),
    re.compile(r"\bEACCES\b"),
)

# A denial phrase names the refusal; a write-operation shape names what was
# refused. Both must be present on the line, so output that merely *mentions* a
# denial about the user's code (a policy error, an auth failure) is not mistaken
# for a sandbox-denied write. ``operation not permitted`` is EPERM's English
# spelling, so it belongs with the denial phrases — never the write-operation
# set, where it would classify on its own. The bare ``open`` token is only a
# write shape with the libc/syscall punctuation (``open:`` / ``open '`` /
# ``open(``) a real denied open prints; a sentence *about* opening something
# (``permission denied to open a user file``) is not.
_DENIAL_PHRASE_RE = re.compile(
    r"permission denied|operation not permitted|\bEPERM\b", re.IGNORECASE
)
_WRITE_OPERATION_RE = re.compile(
    r"\b(?:mkdir|cp|touch|cannot create)\b"
    r"|open\s*[:(]"
    r"|open\s*'",
    re.IGNORECASE,
)

_IPV4_RE = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")
_LOOPBACK_HOST_RE = re.compile(r"\blocalhost\b", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class SandboxFailure:
    """A classified sandbox-caused failure: the reason and the matched line."""

    reason: str
    line: str


def _refused_target_is_loopback(text: str) -> bool:
    """Whether a ``connection refused`` message names only loopback targets.

    ``connect to 127.0.0.1 port 8080 failed: Connection refused`` is the gate's
    own server, not the sandbox denying egress, so it must stay unclassified.
    Any non-loopback IPv4 literal or host name makes the refusal a sandbox
    signature.
    """
    addresses = _IPV4_RE.findall(text)
    if addresses:
        return all(address.startswith("127.") for address in addresses)
    return bool(_LOOPBACK_HOST_RE.search(text))


def _reason_for_line(line: str) -> str | None:
    for pattern in _NETWORK_PATTERNS:
        if pattern.search(line):
            return NETWORK_DISABLED_REASON
    if _CONNECTION_REFUSED_RE.search(line) and not _refused_target_is_loopback(line):
        return NETWORK_DISABLED_REASON
    for pattern in _WRITE_PATTERNS:
        if pattern.search(line):
            return PATH_NOT_WRITABLE_REASON
    if _DENIAL_PHRASE_RE.search(line) and _WRITE_OPERATION_RE.search(line):
        return PATH_NOT_WRITABLE_REASON
    return None


def classify_sandbox_failure_detail(text: str) -> SandboxFailure | None:
    """Return the first sandbox-shaped line in ``text`` and its reason, or ``None``.

    Scans line by line so a single unclassified line (a real lint error) never
    hides a later sandbox signature, and so the caller can keep the matched
    line in the outcome without echoing the whole captured output.
    """
    if not text:
        return None
    for raw_line in text.splitlines():
        reason = _reason_for_line(raw_line)
        if reason is not None:
            return SandboxFailure(reason=reason, line=raw_line.strip())
    return None


def classify_sandbox_failure(text: str) -> str | None:
    """Return the sandbox reason for ``text``, or ``None`` when it is the gate's own result."""
    detail = classify_sandbox_failure_detail(text)
    return detail.reason if detail is not None else None


__all__ = [
    "NETWORK_DISABLED_REASON",
    "PATH_NOT_WRITABLE_REASON",
    "SandboxFailure",
    "classify_sandbox_failure",
    "classify_sandbox_failure_detail",
]
