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
    "make: *** [lint] Error 1",
    "connect to 127.0.0.1 port 8080 failed: Connection refused",
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


@pytest.mark.parametrize("sample", ORDINARY_SAMPLES)
def test_ordinary_tool_output_is_left_unclassified(sample: str) -> None:
    assert _classifier()(sample) is None
