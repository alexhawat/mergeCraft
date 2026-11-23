"""Hatch build hook — stamp git HEAD into ``_build_metadata.py`` for wheels/sdists."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from typing import Any

from hatchling.builders.hooks.plugin.interface import BuildHookInterface

_METADATA_TEMPLATE = '''"""Build-time metadata for installed distributions.

The hatch ``build-commit`` hook overwrites this file in wheel/sdist artifacts
only; the source tree keeps ``None`` until a build stamps the git SHA.
"""

from __future__ import annotations

__commit__: str | None = {commit!r}
'''


class BuildCommitHook(BuildHookInterface):
    """Stamp ``mergecraft._build_metadata.__commit__`` from ``git rev-parse HEAD``."""

    PLUGIN_NAME = "custom"

    def initialize(self, version: str, build_data: dict[str, Any]) -> None:
        commit = self._git_head_commit()
        if commit is None:
            return

        self._stamp_dir = tempfile.TemporaryDirectory(prefix="mergecraft-build-")
        out_dir = Path(self._stamp_dir.name)
        out_path = out_dir / "_build_metadata.py"
        out_path.write_text(_METADATA_TEMPLATE.format(commit=commit), encoding="utf-8")

        force_include = build_data.setdefault("force_include", {})
        if self.target_name == "sdist":
            dest = "src/mergecraft/_build_metadata.py"
        else:
            dest = "mergecraft/_build_metadata.py"
        force_include[str(out_path)] = dest

    def finalize(self, version: str, build_data: dict[str, Any], artifact_path: str) -> None:
        if hasattr(self, "_stamp_dir"):
            self._stamp_dir.cleanup()

    def _git_head_commit(self) -> str | None:
        try:
            output = subprocess.check_output(
                ["git", "rev-parse", "HEAD"],
                cwd=self.root,
                text=True,
                stderr=subprocess.DEVNULL,
            )
        except (OSError, subprocess.CalledProcessError):
            return None
        commit = output.strip()
        return commit or None
