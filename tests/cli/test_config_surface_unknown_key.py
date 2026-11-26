"""``config show`` / ``config explain`` treat an unknown key as a usage error (#1569).

``docs/EXIT-CODES.md`` reserves exit ``2`` for an unknown id (``lens show``,
``evidence show``, …). Both config commands caught ``KeyError`` and called
``cli_bail(str(exc))``, which exits ``30`` and re-quotes the message through
``str(KeyError(...))``.

Contract: both commands exit ``CLI_USAGE_EXIT_CODE`` and print the message once,
without the extra pair of quotes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from tests.support.cli_text import compact_cli_text
from typer.testing import CliRunner

from mergecraft.cli.app import app
from mergecraft.cli.exits import CLI_USAGE_EXIT_CODE

if TYPE_CHECKING:
    from pathlib import Path

    from _pytest.monkeypatch import MonkeyPatch

runner = CliRunner()
_DUMB_ENV = {"TERM": "dumb", "NO_COLOR": "1"}

_EXPECTED = "unsupported config key for show/explain: 'bogus.key'"


@pytest.mark.parametrize("verb", ["show", "explain"])
def test_unknown_config_key_exits_usage(
    verb: str,
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Bug: an unknown key is a usage error with a plain, once-printed message."""
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["config", verb, "bogus.key"], env=_DUMB_ENV)

    output = compact_cli_text(result.stdout + result.stderr)
    assert result.exit_code == CLI_USAGE_EXIT_CODE, output
    assert _EXPECTED in output
    assert not output.startswith('"'), output
    assert output.count(_EXPECTED) == 1, output
