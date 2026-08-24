"""Build-time metadata for installed distributions.

The hatch ``build-commit`` hook overwrites this file in wheel/sdist artifacts
only; the source tree keeps ``None`` until a build stamps the git SHA.
"""

from __future__ import annotations

__commit__: str | None = None
