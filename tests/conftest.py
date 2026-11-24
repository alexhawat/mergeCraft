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

# Honesty-checker negative fixtures (tests/scripts/fixtures/test_honesty/) are not pytest modules.
collect_ignore = ["scripts/fixtures"]

pytest_plugins = [
    "tests.support.hermetic",
    "tests.support.github_fakes",
    "tests.support.tracing",
    "tests.support.provider_harness.pytest_plugin",
    "tests.tracing.streaming.conftest",
]


def pytest_configure(config: pytest.Config) -> None:
    """Register the ``hermetic_integration`` marker for collection.

    The canonical declaration lives in ``[tool.pytest.ini_options].markers`` in
    ``pyproject.toml`` (pinned by ``tests/ci/test_integration_job_ran.py``).
    This hook keeps the suite collectible under ``--strict-markers`` in the
    window before that declaration lands; it changes no marker selection.
    """
    config.addinivalue_line(
        "markers",
        "hermetic_integration: keyless integration tests selected by make test-integration",
    )


@pytest.fixture(autouse=True)
def _restore_loguru_stderr() -> Iterator[None]:
    """Detach any stderr sink a test configured on a temporary capture stream."""
    from mergecraft.utils import log

    handler_id = log._STDERR_HANDLER_ID
    yield
    if handler_id != log._STDERR_HANDLER_ID:
        log.configure_logging(force=True)


@pytest.fixture(autouse=True)
def _reset_process_tracer_cache() -> Iterator[None]:
    """Reset the process-wide Tracer cache (#292) so tests do not leak tracers."""
    from mergecraft.tracing.tracer import reset_process_tracer_cache

    reset_process_tracer_cache()
    yield
    reset_process_tracer_cache()


@pytest.fixture(autouse=True)
def _reset_run_scope_settings_snapshot() -> Iterator[None]:
    """Clear run-scope settings ContextVar state so tests do not leak snapshots."""
    from mergecraft.config.settings_snapshot import reset_gateway_settings_cache

    reset_gateway_settings_cache()
    yield
    reset_gateway_settings_cache()


@pytest.fixture(autouse=True)
def _isolate_git_setup_run_state() -> Iterator[None]:
    """Restore ``git_setup``'s per-run module state so tests do not leak it.

    ``create_temp_directory`` and the ``register_*`` helpers record the active
    temp dir and owned paths in module globals and write ``MERGECRAFT_TEMP_DIR``
    straight into ``os.environ``. A test that left those behind changed which
    branches the next test in the same worker took, so the module's measured
    coverage depended on shard membership. The two ``atexit`` flags are left
    alone: the handlers they record really do stay registered for the process.
    """
    from mergecraft.utils import git_setup

    temp_dir = git_setup._temp_dir
    env_temp_dir = os.environ.get("MERGECRAFT_TEMP_DIR")
    created_paths = set(git_setup._created_paths)
    run_owned_dirs = set(git_setup._run_owned_dirs)
    cleanup_at_exit = dict(git_setup._cleanup_at_exit)
    agent_export_dirs = dict(git_setup._agent_export_dirs)
    yield
    git_setup._temp_dir = temp_dir
    if env_temp_dir is None:
        os.environ.pop("MERGECRAFT_TEMP_DIR", None)
    else:
        os.environ["MERGECRAFT_TEMP_DIR"] = env_temp_dir
    git_setup._created_paths.clear()
    git_setup._created_paths.update(created_paths)
    git_setup._run_owned_dirs.clear()
    git_setup._run_owned_dirs.update(run_owned_dirs)
    git_setup._cleanup_at_exit.clear()
    git_setup._cleanup_at_exit.update(cleanup_at_exit)
    git_setup._agent_export_dirs.clear()
    git_setup._agent_export_dirs.update(agent_export_dirs)


@pytest.fixture(autouse=True)
def _clear_ambient_github_event(monkeypatch: pytest.MonkeyPatch) -> None:
    """Clear the runner's ``GITHUB_EVENT_*`` so no test inherits it (#760, F3).

    A test that wants an event opts in with ``monkeypatch.setenv`` after this
    fixture has run; that explicit value still wins, and ``monkeypatch``
    restores the original environment at teardown.
    """
    monkeypatch.delenv("GITHUB_EVENT_NAME", raising=False)
    monkeypatch.delenv("GITHUB_EVENT_PATH", raising=False)


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
# A — xpass ratchet (CQ-1): fail session when XPASSes remain
# ---------------------------------------------------------------------------


def _load_check_xpass() -> Any:
    """Load ``scripts/check_xpass.py`` via importlib for the session hook.

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


@pytest.fixture(scope="session", autouse=True)
def _venv_inode_guard() -> Iterator[None]:
    """Session guard: detect replacement of ``sys.prefix`` (MCB-23 / AG1.7).

    Limit: catches directory replacement, not an in-place ``uv sync`` that adds
    packages to the same directory inode.
    """
    baseline = Path(sys.prefix).stat().st_ino
    yield
    assert Path(sys.prefix).stat().st_ino == baseline


def pytest_sessionfinish(session: pytest.Session, exitstatus: int | pytest.ExitCode) -> None:
    """Fail the session when any XPASS slipped through (CQ-1 / #276)."""
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
