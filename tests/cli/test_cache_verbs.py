"""CC4 — ``mergecraft cache`` verbs (`.ignorelocal/02-cli-sources-trust-wave-plan.md`).

Authoring wave: **CC4.1** (RED). Implementation: **CC4.2**.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from typer.testing import CliRunner

from mergecraft.cli.app import app
from mergecraft.utils.run_cache import RunCache

if TYPE_CHECKING:
    from pathlib import Path

    from _pytest.monkeypatch import MonkeyPatch

runner = CliRunner()
_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def _plain(text: str) -> str:
    return _ANSI.sub("", text)


def test_cache_info_clear_prune(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """``cache info``, ``cache clear``, and ``cache prune`` manage the run cache."""
    cache_root = tmp_path / "run-cache"
    monkeypatch.setenv("MERGECRAFT_CACHE_DIR", str(cache_root))
    monkeypatch.setenv("MERGECRAFT_CACHE_MAX_BYTES", "500")

    cache = RunCache(root=cache_root, max_bytes=500)
    cache.put("alpha", b"x" * 200)

    info = runner.invoke(app, ["cache", "info"], env={"NO_COLOR": "1"})
    info_out = _plain(info.stdout + info.stderr)
    assert info.exit_code == 0, info_out
    assert "200" in info_out or "bytes" in info_out.lower()

    clear = runner.invoke(app, ["cache", "clear"], env={"NO_COLOR": "1"})
    assert clear.exit_code == 0, _plain(clear.stdout + clear.stderr)
    assert cache.get("alpha") is None

    cache.put("beta", b"y" * 300)
    cache.put("gamma", b"z" * 300)
    prune = runner.invoke(app, ["cache", "prune"], env={"NO_COLOR": "1"})
    prune_out = _plain(prune.stdout + prune.stderr)
    assert prune.exit_code == 0, prune_out
    assert cache.total_bytes() <= 500
