"""The sandbox failure signature table classifies sandbox-caused exit output.

A gate that fails because the sandbox denied it network or a write produced no
verdict about the diff; reporting it as a finding invents a code defect. The
table maps the signature stderr to a named reason and leaves ordinary tool
output alone — even output that happens to mention "network".
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from mergecraft.analyzers.redact import redact_analyzer_output
from tests.analyzers.support import import_module

NETWORK_REASON = "sandboxed: network is disabled"
WRITE_REASON = "sandboxed: path not writable"

NETWORK_SAMPLES: tuple[str, ...] = (
    "Temporary failure in name resolution",
    "Could not resolve host: registry.npmjs.org",
    "Network is unreachable",
    "connect: ENETUNREACH",
    "getaddrinfo EAI_AGAIN registry.npmjs.org",
    "connect to 93.184.216.34 port 443 failed: Connection refused",
)

WRITE_SAMPLES: tuple[str, ...] = (
    "EROFS: read-only file system, open '/opt/mergecraft/build.log'",
    "Read-only file system",
    "EACCES: permission denied, open '/opt/mergecraft/.venv/pyvenv.cfg'",
)

ORDINARY_SAMPLES: tuple[str, ...] = (
    "src/app.py:3:1: error: network security is not configured",
    "ruff check failed: the `network` fixture is unused (F841)",
    # A lint message *about the user's code* names a helper, not a denied syscall;
    # the denial phrase alone must not classify it.
    "src/app.py:3:1: error: permission denied to call the network helper",
    # A package-manager policy message, not the kernel refusing a write.
    "npm ERR! permission denied by policy",
    # A build tool's own error line carries no sandbox write shape.
    "make: *** [lint] Error 1",
    "connect to 127.0.0.1 port 8080 failed: Connection refused",
    # A package manager reporting a policy denial: the denial phrase is present
    # but no write operation is named, so this is ordinary tool output.
    "npm ERR! operation not permitted by policy",
    # An application-level authorization error that reuses the phrase.
    "AuthError: operation not permitted for this role",
    # A test assertion whose message happens to contain the phrase.
    "test_auth.py:22: AssertionError: operation not permitted",
    # An authz log line, not a kernel denial of a write syscall.
    "authorization: operation not permitted on this resource",
    # Prose about the policy ("operation is not permitted"), not a denial phrase.
    "error: the operation is not permitted by the current policy",
    # A lint error *about code* opening a file; the generic ``open`` token must
    # not let a code-level sentence self-satisfy the write rule.
    "src/policy.py:10:1: error: permission denied to open a user file",
    # An assertion message mentioning ``open``, again code, not a denied syscall.
    "AssertionError: permission denied to open the vault",
)

# A denied write leaves the kernel's ``Permission denied`` spelling and an
# absolute path. ``run.py`` redacts the gate's output *before* classification,
# and the redactor replaces that absolute path with ``<redacted>``; the classifier
# therefore sees the line below, not the raw one, and must still name the reason.
REDACTED_DENIED_WRITE = "mkdir: cannot create directory '<redacted>': Permission denied"

# Positive matrix: the write-denied shapes that must *still* classify once the
# denial-phrase rule is tightened. Each names a real kernel/errno write denial —
# a write operation on a path, or an errno token — never a code-level sentence.
# These are the true positives the tightened classifier has to keep.
WRITE_POSITIVE_SAMPLES: tuple[str, ...] = (
    "mkdir: cannot create directory '<redacted>': Permission denied",
    "mkdir: cannot create directory '/workspace/build': Permission denied",
    "cp: cannot create regular file '/opt/mergecraft/x': Permission denied",
    "touch: cannot touch '/x/y': Permission denied",
    "open: permission denied",
    "npm ERR! EACCES: permission denied, mkdir '<redacted>'",
    "EPERM: operation not permitted, open '/workspace/.venv'",
    "EROFS: read-only file system, open '<redacted>.log'",
)


def _classifier() -> Callable[[str], str | None]:
    module = import_module("mergecraft.analyzers.sandbox_failures")
    for name in ("classify_sandbox_failure", "sandbox_failure_reason", "classify_stderr"):
        candidate: Any = getattr(module, name, None)
        if callable(candidate):
            return candidate
    raise AssertionError(
        "mergecraft.analyzers.sandbox_failures must expose a stderr classifier "
        "(classify_sandbox_failure)"
    )


@pytest.mark.parametrize("sample", NETWORK_SAMPLES)
def test_network_signatures_classify_as_network_disabled(sample: str) -> None:
    assert _classifier()(sample) == NETWORK_REASON


@pytest.mark.parametrize("sample", WRITE_SAMPLES)
def test_write_denied_signatures_classify_as_path_not_writable(sample: str) -> None:
    assert _classifier()(sample) == WRITE_REASON


@pytest.mark.parametrize("sample", WRITE_POSITIVE_SAMPLES)
def test_write_denied_positive_matrix_still_classifies(sample: str) -> None:
    """Tightening the denial rule must not drop a real denied write.

    The ordinary-output negatives above are pinned so a code-level sentence stops
    classifying; these are the counterpart true positives that must survive the
    same tightening.
    """
    assert _classifier()(sample) == WRITE_REASON


@pytest.mark.parametrize("sample", ORDINARY_SAMPLES)
def test_ordinary_tool_output_is_left_unclassified(sample: str) -> None:
    assert _classifier()(sample) is None


def test_redacted_write_denied_line_classifies_as_path_not_writable() -> None:
    """A pre-redacted denied write still names *"sandboxed: path not writable"*.

    ``run.py`` calls ``redact_analyzer_output`` before the classifier reads the
    gate's output, so the realistic ``Permission denied`` shape arrives with its
    absolute path replaced by ``<redacted>``. The classifier must recognize the
    denied write from the operation itself; keying the reason on an absolute path
    on the same line lets the redactor defeat it, and the sandbox denial is then
    reported as a finding (P-8).
    """
    raw = "mkdir: cannot create directory '/workspace/build': Permission denied"
    redacted = redact_analyzer_output(raw, tool_id="gate")

    assert redacted == REDACTED_DENIED_WRITE, redacted
    assert _classifier()(REDACTED_DENIED_WRITE) == WRITE_REASON


@pytest.mark.parametrize("sample", WRITE_SAMPLES)
def test_errno_write_signatures_survive_redaction(sample: str) -> None:
    """The errno spellings still classify on the line the classifier actually sees."""
    redacted = redact_analyzer_output(sample, tool_id="gate")
    assert _classifier()(redacted) == WRITE_REASON, redacted
