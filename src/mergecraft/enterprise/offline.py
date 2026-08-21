"""Offline / self-hosted install path for enterprise deployments (#381, D14).

Runtime only — no standalone binary.  Cites the Python 3.11 floor from
``docs/dev/python-version-floor.md`` (#343).

Exports:
    OfflineInstallError: Raised when an unsupported install method is requested.
    OfflineInstallPlan: Dataclass describing the offline install contract.
    offline_install_plan: Return the offline install plan for mergeCraft.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

__all__ = [
    "OfflineInstallError",
    "OfflineInstallPlan",
    "offline_install_plan",
]

_FLOOR_DOC = Path("docs/dev/python-version-floor.md")
_PYTHON_REQUIRES = ">=3.11"


class OfflineInstallError(Exception):
    """Raised when an unsupported offline install method is requested (D14)."""


@dataclass(frozen=True)
class OfflineInstallPlan:
    """Describes the supported offline install contract for mergeCraft.

    Attributes:
        python_requires: PEP 440 specifier for the minimum Python version.
        standalone_binary: Always ``False`` per D14 — no PyOxidizer bundle.
        floor_doc: Repo-relative path to the Python version floor ADR.
        artifacts: Supported offline distribution artifacts.
    """

    python_requires: str
    standalone_binary: bool
    floor_doc: Path
    artifacts: list[Any] = field(default_factory=list)


def offline_install_plan(*, want_binary: bool = False) -> OfflineInstallPlan:
    """Return the offline install plan for mergeCraft.

    Args:
        want_binary: If ``True``, raise :class:`OfflineInstallError` — a
            standalone binary is not supported (D14).

    Returns:
        An :class:`OfflineInstallPlan` describing wheel/sdist/Docker artifacts
        and citing ``docs/dev/python-version-floor.md``.

    Raises:
        OfflineInstallError: When ``want_binary=True`` (D14 — no binary).
    """
    if want_binary:
        msg = (
            "standalone binary packaging is not supported (D14). "
            "Use the wheel/sdist or the Docker image instead."
        )
        raise OfflineInstallError(msg)

    return OfflineInstallPlan(
        python_requires=_PYTHON_REQUIRES,
        standalone_binary=False,
        floor_doc=_FLOOR_DOC,
        artifacts=[
            "wheel: merge-craft-<version>-py3-none-any.whl",
            "sdist: merge-craft-<version>.tar.gz",
            "docker: ghcr.io/alexhawat/mergecraft:<version>",
        ],
    )
