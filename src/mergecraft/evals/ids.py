"""Shared identifier patterns for the eval bank."""

from __future__ import annotations

import re
from typing import Final

# Token shape for case IDs — safe to use as filenames and Python identifiers.
CASE_ID_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\-]{0,127}$")

__all__ = ["CASE_ID_RE"]
