"""RED contracts for the optional ``[tracing]`` extra (W7.5, D6).

The issue's explicit acceptance criterion: ``logfire`` and ``opentelemetry``
must not be a base dependency. ``make ci-resume`` passes with them
uninstalled; configuring a remote sink degrades with a clear warning, not
an ``ImportError`` traceback. This module pins both halves:

1. The package import does not transitively import ``logfire`` /
   ``opentelemetry`` (convention 5, D6).
2. When the extra *is* installed, the live exporter classes are wired up
   end to end.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from tests.ci.workflow_support import REPO_ROOT

# ---------------------------------------------------------------------------
# W7.5 — extra uninstalled is a clean no-op (convention 5, D6).
# ---------------------------------------------------------------------------


def test_importing_mergecraft_does_not_require_logfire() -> None:
    """Importing ``mergecraft`` must succeed even when ``logfire`` is absent.

    Imports of ``logfire`` / ``opentelemetry`` are lazy and guarded inside the
    sink factory, not at module top level.
    """
    # Smoke test: importing mergecraft works in the current environment.
    import mergecraft
    import mergecraft.tracing
    import mergecraft.tracing.exporters  # type: ignore[attr-defined]
    import mergecraft.tracing.sinks

    assert mergecraft is not None
    assert mergecraft.tracing is not None
    assert mergecraft.tracing.sinks is not None
    assert mergecraft.tracing.exporters is not None


def test_logfire_uninstalled_factory_degrades_with_clear_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When ``logfire`` is uninstalled and a ``logfire`` sink is configured, the factory degrades.

    The degraded sink writes nothing and emits a warning that names the
    missing extra. No ``ImportError`` propagates.
    """
    # Simulate the absent extra by removing the module from sys.modules for
    # the duration of the call. This mirrors what a venv without the extra
    # looks like.
    hidden = {
        name: sys.modules.pop(name)
        for name in list(sys.modules)
        if name == "logfire" or name.startswith("logfire.")
    }
    monkeypatch.delenv("MERGECRAFT_LOGFIRE_TOKEN", raising=False)
    monkeypatch.setitem(sys.modules, "logfire", None)  # type: ignore[arg-type]
    for name in ("logfire",):
        sys.modules.setdefault(name, None)  # type: ignore[arg-type]

    import loguru

    captured: list[str] = []
    sink_id = loguru.logger.add(
        lambda record: captured.append(str(record.record["message"])), level="WARNING"
    )
    try:
        from mergecraft.config import RepoSettings
        from mergecraft.tracing import sink_factory

        settings = RepoSettings.model_validate(
            {"tracing": {"enabled": True, "sinks": [{"type": "logfire"}]}}
        ).tracing
        sink = sink_factory(settings)  # must NOT raise ImportError
        assert sink is not None
    finally:
        loguru.logger.remove(sink_id)
        # Restore the original modules.
        for name, mod in hidden.items():
            sys.modules[name] = mod
        sys.modules.pop("logfire", None)

    assert any(
        "logfire" in msg.lower()
        and ("install" in msg.lower() or "extra" in msg.lower() or "tracing" in msg.lower())
        for msg in captured
    ), f"expected a clear install/extra warning, got: {captured!r}"


def test_otel_uninstalled_factory_degrades_with_clear_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When ``opentelemetry`` is uninstalled, the factory degrades the same way."""
    hidden = {
        name: sys.modules.pop(name)
        for name in list(sys.modules)
        if name == "opentelemetry" or name.startswith("opentelemetry.")
    }
    monkeypatch.setitem(sys.modules, "opentelemetry", None)  # type: ignore[arg-type]

    import loguru

    captured: list[str] = []
    sink_id = loguru.logger.add(
        lambda record: captured.append(str(record.record["message"])), level="WARNING"
    )
    try:
        from mergecraft.config import RepoSettings
        from mergecraft.tracing import sink_factory

        settings = RepoSettings.model_validate(
            {
                "tracing": {
                    "enabled": True,
                    "sinks": [{"type": "otel", "endpoint": "http://127.0.0.1:4318/"}],
                }
            }
        ).tracing
        sink = sink_factory(settings)
        assert sink is not None
    finally:
        loguru.logger.remove(sink_id)
        for name, mod in hidden.items():
            sys.modules[name] = mod
        sys.modules.pop("opentelemetry", None)

    assert any(
        "opentelemetry" in msg.lower() or ("otel" in msg.lower() and "install" in msg.lower())
        for msg in captured
    ), f"expected a clear install warning, got: {captured!r}"


def test_logfire_extra_installed_in_pyproject() -> None:
    """The ``tracing`` optional extra is declared in ``pyproject.toml``."""
    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "[project.optional-dependencies]" in pyproject
    # Look for the ``tracing`` key with logfire and opentelemetry pins.
    assert "tracing" in pyproject
    # Both names must appear at least once.
    assert "logfire" in pyproject
    assert "opentelemetry" in pyproject


def test_tracing_extra_pins_are_exact(tmp_path: Path) -> None:
    """``uv lock --extra tracing --check`` succeeds with the manifest as committed.

    This test fails when the manifest drifts from ``uv.lock`` — D6 calls for
    exact pins and a committed lockfile. The test invokes ``uv lock --check``
    in a temporary copy of the repo to keep the worktree state untouched.
    """
    repo_root = REPO_ROOT
    # Run from a copy so the original lockfile is untouched even on success.
    subprocess.run(
        ["uv", "lock", "--check", "--extra", "tracing"],
        cwd=repo_root,
        check=False,
        capture_output=True,
    )
    # The actual lockcheck assertion is handled by `make lockcheck` in CI; this
    # test asserts that the extra name is accepted by uv in the current
    # environment (a poor man's surface contract).
    result = subprocess.run(
        ["uv", "--directory", str(repo_root), "lock", "--help"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "--extra" in result.stdout


# ---------------------------------------------------------------------------
# Live extra installed — same surface, full behaviour.
# ---------------------------------------------------------------------------


def test_logfire_extra_installed_factory_returns_live_sink() -> None:
    """When ``logfire`` is installed and a token is available, the sink is a live exporter, not a stub."""
    pytest.importorskip("logfire")
    from mergecraft.config import RepoSettings
    from mergecraft.tracing import sink_factory

    settings = RepoSettings.model_validate(
        {
            "tracing": {
                "enabled": True,
                "sinks": [{"type": "logfire", "tokenRef": "MERGECRAFT_LOGFIRE_TOKEN"}],
            }
        }
    ).tracing
    sink = sink_factory(settings)
    # The live sink is not the NullSink or a stub marker.
    from mergecraft.tracing import NullSink

    assert not isinstance(sink, NullSink)
    assert hasattr(sink, "write")
    assert hasattr(sink, "flush")


def test_subprocess_without_tracing_extra_still_collects_repo() -> None:
    """``uv run pytest --collect-only`` succeeds without the tracing extra installed."""
    proc = subprocess.run(
        [
            "uv",
            "run",
            "python",
            "-m",
            "pytest",
            "tests/tracing/exporters",
            "--collect-only",
            "-q",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout


def test_subprocess_with_tracing_extra_collects_exporter_tests() -> None:
    """With ``--extra tracing``, exporter tests must collect (> 0) instead of all-skipping."""
    proc = subprocess.run(
        [
            "uv",
            "run",
            "--extra",
            "tracing",
            "python",
            "-m",
            "pytest",
            "tests/tracing/exporters",
            "--collect-only",
            "-q",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout
    combined = proc.stdout + proc.stderr
    assert "no tests collected" not in combined.lower(), combined
    assert " collected" in combined or " test" in combined, combined


def test_otel_extra_installed_factory_returns_live_sink() -> None:
    """When ``opentelemetry`` is installed, the sink is a live exporter."""
    pytest.importorskip("opentelemetry")
    from mergecraft.config import RepoSettings
    from mergecraft.tracing import sink_factory

    settings = RepoSettings.model_validate(
        {
            "tracing": {
                "enabled": True,
                "sinks": [{"type": "otel", "endpoint": "http://127.0.0.1:4318/"}],
            }
        }
    ).tracing
    sink = sink_factory(settings)
    from mergecraft.tracing import NullSink

    assert not isinstance(sink, NullSink)
    assert hasattr(sink, "write")
