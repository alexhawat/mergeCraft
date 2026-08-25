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

from mergecraft.version_info import (
    format_version_display,
    short_commit,
    version_json_payload,
)

__all__ = [
    "__commit__",
    "__version__",
    "format_version_display",
    "short_commit",
    "version_json_payload",
]


def __getattr__(name: str) -> Any:
    """Lazy ``__commit__`` — avoid subprocess/git work on ``import mergecraft``."""
    if name == "__commit__":
        from mergecraft.build_metadata import resolve_build_commit

        return resolve_build_commit()
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)
