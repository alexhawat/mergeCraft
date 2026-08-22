"""Operational diagnostics for enterprise / server deployments (#381).

Exports:
    operational_diagnostics: Return a dict of runtime and environment info.
"""

from __future__ import annotations

import platform
import sys
from typing import Any

__all__ = [
    "operational_diagnostics",
]


def operational_diagnostics() -> dict[str, Any]:
    """Return a dictionary of runtime and environment diagnostics.

    The returned dict always contains a ``python`` field with the current
    interpreter version string.

    Returns:
        A JSON-serialisable dict with at least ``{"python": "<version>"}``.
    """
    return {
        "python": sys.version,
        "python_version_info": {
            "major": sys.version_info.major,
            "minor": sys.version_info.minor,
            "micro": sys.version_info.micro,
        },
        "platform": platform.platform(),
        "machine": platform.machine(),
        "implementation": platform.python_implementation(),
    }
