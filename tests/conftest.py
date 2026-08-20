"""Ensure repo root is on ``sys.path`` for ``tests.*`` imports."""

from __future__ import annotations

import importlib.util
import os
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

pytest_plugins = ["tests.orchestrator.conftest", "tests.support.provider_harness.pytest_plugin"]


@pytest.fixture(autouse=True)
def _reset_process_tracer_cache() -> Iterator[None]:
    """Reset the process-wide Tracer cache (#292) so tests do not leak tracers."""
    from mergecraft.tracing.tracer import reset_process_tracer_cache

    reset_process_tracer_cache()
    yield
    reset_process_tracer_cache()


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
    """Load ``scripts/check_xpass.py`` via importlib (single source for D6 list).

    Raises:
        SystemExit: When the module cannot be loaded (fail-closed — aborts the session).
    """
    path = _ROOT / "scripts" / "check_xpass.py"
    spec = importlib.util.spec_from_file_location("_check_xpass_hook", path)
    if spec is None or spec.loader is None:
        pytest.exit(
            f"xpass-ratchet: cannot load {path} — ensure scripts/check_xpass.py exists",
            returncode=3,
        )
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

    mod = _load_check_xpass()

    xpassed = tr.stats.get("xpassed", [])
    if not xpassed:
        return

    records = tuple(mod.XpassRecord(nodeid=r.nodeid, reason="") for r in xpassed)
    inventory = mod.XpassInventory(records=records)
    rc = mod.check_xpass(inventory)
    if rc != 0 and exitstatus == 0:
        session.exitstatus = 1
