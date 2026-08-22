"""``mergecraft.__version__`` must track the distribution version.

The number was restated as a literal in ``mergecraft/__init__.py`` and drifted:
``pyproject.toml`` moved to ``0.1.0a1`` while the literal stayed at ``0.1.0``,
so ``mergecraft --version`` under-reported the release. It also keys the offline
result cache and is stamped on telemetry and eval reproducibility pins, so the
two disagreeing quietly mixes artefacts across builds.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import mergecraft

_PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"


def _declared_version() -> str:
    data = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))
    version = data["project"]["version"]
    assert isinstance(version, str)
    return version


def test_version_matches_pyproject() -> None:
    assert mergecraft.__version__ == _declared_version()


def test_version_is_resolved_not_a_placeholder() -> None:
    """A missing distribution must not pass as a real version."""
    assert mergecraft.__version__ != "0.0.0+unknown", (
        "no installed `merge-craft` distribution — run `make install` "
        "(a placeholder version would poison cache keys and telemetry)"
    )
