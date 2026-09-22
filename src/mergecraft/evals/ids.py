"""Shared identifier patterns for the eval bank."""

from __future__ import annotations

import re
from typing import Final

# Token shape for case IDs — safe to use as filenames and Python identifiers.
# Anchored with ``\Z`` (not ``$``): ``$`` also matches just before a trailing
# newline, so ``"a\n"`` would slip through and become a filename with a
# newline in it. ``\Z`` matches only the true end of the string.
CASE_ID_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\-]{0,127}\Z")

__all__ = ["CASE_ID_RE"]
