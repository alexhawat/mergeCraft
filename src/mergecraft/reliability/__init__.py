"""Recovery cleanup and redacted diagnostic-bundle surfaces (#365).

Exports:
    cleanup_on_failure: Cleanup for timeout, cancel, and crash modes.
    write_diagnostic_bundle: Operator bundle with secrets redacted.
"""

from __future__ import annotations

from mergecraft.reliability.diagnostic_bundle import write_diagnostic_bundle
from mergecraft.reliability.recovery import cleanup_on_failure

__all__ = [
    "cleanup_on_failure",
    "write_diagnostic_bundle",
]
