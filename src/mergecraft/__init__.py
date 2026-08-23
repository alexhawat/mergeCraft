"""mergecraft — standalone BYOK GitHub Action runtime (Python)."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _distribution_version
from typing import Any

# Read from the installed distribution rather than restating the number here.
# A literal drifted once already: `pyproject.toml` moved to the alpha while this
# stayed at "0.1.0", so `mergecraft --version` under-reported the release. The
# value is not cosmetic — it keys the offline result cache and is stamped on
# telemetry and eval reproducibility pins, so a wrong version silently mixes
# artefacts from different builds.
try:
    __version__ = _distribution_version("merge-craft")
except PackageNotFoundError:  # pragma: no cover — source tree with nothing installed
    __version__ = "0.0.0+unknown"

# Optional full build commit SHA baked in at release time; ``None`` when unknown.
__commit__: str | None = None


def short_commit(commit: str | None) -> str | None:
    """Return the seven-character short SHA prefix, or ``None`` when unknown."""
    if commit is None:
        return None
    trimmed = commit.strip()
    if not trimmed:
        return None
    return trimmed[:7]


def format_version_display(version: str, commit: str | None) -> str:
    """Render ``<version> (<short-sha>)`` when commit is known; else ``version`` alone."""
    short = short_commit(commit)
    if short is None:
        return version
    return f"{version} ({short})"


def version_json_payload(version: str, commit: str | None) -> dict[str, Any]:
    """Machine-readable version document (``schema_version`` added by the CLI envelope)."""
    return {
        "version": version,
        "commit": short_commit(commit),
    }


__all__ = [
    "__commit__",
    "__version__",
    "format_version_display",
    "short_commit",
    "version_json_payload",
]
