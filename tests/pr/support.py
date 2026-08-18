"""Lazy imports for DG8 PR utility modules (RED before DG8.2)."""

from __future__ import annotations

import importlib
from typing import Any


def import_module(dotted: str) -> Any:
    """Import a module that DG8.2 will add under ``src/mergecraft/``."""
    return importlib.import_module(dotted)
