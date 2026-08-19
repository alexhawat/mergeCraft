"""Ensure repo root is on ``sys.path`` for ``tests.*`` imports."""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from typing import Any

import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

pytest_plugins = ["tests.orchestrator.conftest", "tests.support.provider_harness.pytest_plugin"]


# ---------------------------------------------------------------------------
# B — live opt-in once (CQ-2): skip ``live``-marked tests unless opted in
# ---------------------------------------------------------------------------


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Skip ``live``-marked tests unless ``MERGECRAFT_LIVE=1`` (CQ-2 / D8).

    When the flag IS set, individual test bodies call ``_require`` /
    ``pytest.fail`` on missing credentials so the suite stays fail-closed (D9).
    """
    if os.environ.get("MERGECRAFT_LIVE") == "1":
        return
    skip = pytest.mark.skip(reason="MERGECRAFT_LIVE=1 required to run live tests")
    for item in items:
        if item.get_closest_marker("live"):
            item.add_marker(skip)


# ---------------------------------------------------------------------------
# A — xpass ratchet (CQ-1): fail session when non-D6 XPASSes remain
# ---------------------------------------------------------------------------


def _load_check_xpass() -> Any:
    """Load ``scripts/check_xpass.py`` via importlib (single source for D6 list)."""
    path = _ROOT / "scripts" / "check_xpass.py"
    spec = importlib.util.spec_from_file_location("_check_xpass_hook", path)
    if spec is None or spec.loader is None:  # pragma: no cover
        return None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def pytest_sessionfinish(session: pytest.Session, exitstatus: int | pytest.ExitCode) -> None:
    """Fail the session if any non-D6 XPASS slipped through (CQ-1 / #276).

    D6 test paths (``scripts/check_xpass.py::D6_TEST_PATHS``) are excluded —
    those xpasses are counted and printed but do not block the gate.
    """
    tr = session.config.pluginmanager.getplugin("terminalreporter")
    if tr is None:
        return
    xpassed = tr.stats.get("xpassed", [])
    if not xpassed:
        return

    mod = _load_check_xpass()
    if mod is None:  # pragma: no cover
        return

    is_d6 = mod.is_d6_nodeid
    allowed = [r for r in xpassed if not is_d6(r.nodeid)]
    d6_count = len(xpassed) - len(allowed)

    if d6_count:
        tr.write_line(
            f"xpass-ratchet: {d6_count} D6-excluded xpass(es) — not failing the gate.",
        )
    if not allowed:
        return

    tr.write_sep("=", "XPASS RATCHET FAILED", red=True)
    for r in allowed:
        tr.write_line(f"  XPASS {r.nodeid}", red=True)
    tr.write_line(
        f"xpass-ratchet: {len(allowed)} allowed-tree xpass(es); promote or fix these tests.",
        red=True,
    )
    session.exitstatus = 1
