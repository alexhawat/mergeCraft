"""TH1 RED — cheat-signature lint contract (D16, TH7).

``scripts/check_test_cheat_signatures.py`` flags tautological test patterns such as
``getattr(mod, "NAME", <literal>)`` followed by an equality assert on the same literal.
TH7 lands the script and wires it into ``make lint``.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from tests.ci.workflow_support import REPO_ROOT


def test_lint_script_flags_getattr_tautology_fixture(tmp_path: Path) -> None:
    """A temp file with the getattr tautology pattern must make the lint script exit non-zero."""
    cheat_file = tmp_path / "test_cheat_fixture.py"
    cheat_file.write_text(
        "def test_getattr_tautology():\n"
        "    mod = object()\n"
        '    assert getattr(mod, "NAME", "literal") == "literal"\n',
        encoding="utf-8",
    )
    script = REPO_ROOT / "scripts" / "check_test_cheat_signatures.py"
    assert script.is_file(), (
        "scripts/check_test_cheat_signatures.py not yet landed — TH7 must add D16 lint"
    )
    proc = subprocess.run(
        [sys.executable, str(script), str(cheat_file)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode != 0, (
        "cheat-signature lint must reject getattr(mod, NAME, literal) tautologies\n"
        f"{proc.stdout}{proc.stderr}"
    )
