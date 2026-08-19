"""Ensure repo root is on ``sys.path`` for ``tests.*`` imports."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

pytest_plugins = ["tests.orchestrator.conftest", "tests.support.provider_harness.pytest_plugin"]
