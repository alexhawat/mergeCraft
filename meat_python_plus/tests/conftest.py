"""Pytest configuration for meat_python_plus."""

from __future__ import annotations

import sys
from pathlib import Path

# Allow `from _parity_helpers import …` and `from fixtures.go_parity import …`.
_TESTS_DIR = Path(__file__).resolve().parent
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))
