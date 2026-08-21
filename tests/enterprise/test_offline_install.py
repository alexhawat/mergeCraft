"""W7.1 — offline / self-hosted install path (#381, D14).

Runtime only: Python 3.11+ floor from #343. No standalone binary.
Intended public API (W7.2): ``mergecraft.enterprise.offline``.
"""

from __future__ import annotations

import pytest

from tests.ci.workflow_support import REPO_ROOT


def test_offline_install_plan_uses_python_311_floor() -> None:
    """Happy: the offline plan cites the shipped 3.11 floor, not a binary."""
    from mergecraft.enterprise.offline import offline_install_plan

    plan = offline_install_plan()
    assert plan.python_requires == ">=3.11"
    assert plan.standalone_binary is False
    floor_doc = str(plan.floor_doc)
    assert "docs/dev/python-version-floor.md" in floor_doc.replace("\\", "/")


def test_offline_install_plan_names_wheel_or_docker_artifact() -> None:
    """Happy: offline install is a wheel/sdist or image, never an executable bundle."""
    from mergecraft.enterprise.offline import offline_install_plan

    plan = offline_install_plan()
    artifacts = " ".join(str(item).casefold() for item in plan.artifacts)
    assert (
        "wheel" in artifacts or "sdist" in artifacts or "docker" in artifacts or "ghcr" in artifacts
    )
    assert "pyoxidizer" not in artifacts
    assert "standalone" not in artifacts


def test_offline_install_rejects_standalone_binary_request() -> None:
    """Error (D14): requesting a standalone binary is refused by type and message."""
    from mergecraft.enterprise.offline import OfflineInstallError, offline_install_plan

    with pytest.raises(OfflineInstallError, match="standalone binary"):
        offline_install_plan(want_binary=True)


def test_python_version_floor_adr_exists() -> None:
    """GREEN: #343 ADR is the install-floor source; #381 must cite it, not rewrite it."""
    adr = REPO_ROOT / "docs" / "dev" / "python-version-floor.md"
    assert adr.is_file()
    text = adr.read_text(encoding="utf-8")
    assert "3.11" in text
    assert "standalone binary" in text.casefold() or "pyoxidizer" in text.casefold()
