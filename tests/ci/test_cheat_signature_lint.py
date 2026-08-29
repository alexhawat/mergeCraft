"""TH1 RED — cheat-signature lint contract (D16, TH7).

``scripts/check_test_cheat_signatures.py`` flags tautological test patterns such as
``getattr(mod, "NAME", <literal>)`` followed by an equality assert on the same literal.
TH7 lands the script and wires it into ``make lint``.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

from tests.ci.workflow_support import REPO_ROOT


def _cheat_script() -> Path:
    script = REPO_ROOT / "scripts" / "check_test_cheat_signatures.py"
    assert script.is_file(), "scripts/check_test_cheat_signatures.py missing"
    return script


def _run_cheat_lint(path: Path, *, advisory: bool = False) -> subprocess.CompletedProcess[str]:
    cmd = [sys.executable, str(_cheat_script())]
    if advisory:
        cmd.append("--advisory")
    cmd.append(str(path))
    return subprocess.run(
        cmd,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_genuine_tautology_still_errors(tmp_path: Path) -> None:
    """Guard deletion — removing the rule must fail CI on a real tautology."""
    cheat_file = tmp_path / "test_genuine_tautology.py"
    cheat_file.write_text(
        "def test_getattr_tautology():\n"
        "    mod = object()\n"
        '    assert getattr(mod, "NAME", "literal") == "literal"\n',
        encoding="utf-8",
    )
    proc = _run_cheat_lint(cheat_file)
    combined = proc.stdout + proc.stderr
    assert proc.returncode != 0, (
        "getattr tautology lint must block a genuine tautology (D4)\n" + combined
    )
    assert "getattr_tautology" in combined


def test_legitimate_fallback_default_assertion_is_not_flagged(tmp_path: Path) -> None:
    """Legitimate attribute-absent → default asserts must not match the rule."""
    cheat_file = tmp_path / "test_fallback_default.py"
    cheat_file.write_text(
        "class Settings:\n"
        "    pass\n\n"
        "def test_missing_attr_falls_back_to_default():\n"
        "    settings = Settings()\n"
        "    assert getattr(settings, 'missing_attr', 'default') == 'default'\n",
        encoding="utf-8",
    )
    proc = _run_cheat_lint(cheat_file)
    combined = proc.stdout + proc.stderr
    assert proc.returncode == 0, (
        "fallback-default assertion should not be flagged as getattr_tautology\n" + combined
    )
    assert "getattr_tautology" not in combined


def test_getattr_tautology_severity_is_still_error(tmp_path: Path) -> None:
    """``getattr_tautology`` stays severity error — never quietly downgraded (D4)."""
    import sys

    visitors_path = REPO_ROOT / "scripts" / "ast_cheat_visitors.py"
    module_name = "ast_cheat_visitors_test"
    spec = importlib.util.spec_from_file_location(module_name, visitors_path)
    assert spec is not None
    assert spec.loader is not None
    visitors = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = visitors
    spec.loader.exec_module(visitors)

    cheat_file = tmp_path / "test_severity_pin.py"
    cheat_file.write_text(
        "def test_getattr_tautology():\n"
        "    mod = object()\n"
        '    assert getattr(mod, "NAME", "literal") == "literal"\n',
        encoding="utf-8",
    )
    result = visitors.scan_file(cheat_file, repo=REPO_ROOT)
    tautology_hits = [
        finding
        for finding in [*result.errors, *result.warnings]
        if finding.kind == "getattr_tautology"
    ]
    assert tautology_hits, "expected a getattr_tautology finding for the tautology fixture"
    assert all(hit.level == "error" for hit in tautology_hits)


def test_advisory_opt_out_still_works(tmp_path: Path) -> None:
    """``--advisory`` must print findings but exit 0."""
    cheat_file = tmp_path / "test_advisory_opt_out.py"
    cheat_file.write_text(
        "def test_getattr_tautology():\n"
        "    mod = object()\n"
        '    assert getattr(mod, "NAME", "literal") == "literal"\n',
        encoding="utf-8",
    )
    proc = _run_cheat_lint(cheat_file, advisory=True)
    combined = proc.stdout + proc.stderr
    assert proc.returncode == 0, (
        "advisory cheat-signature lint must exit 0 even when findings are present\n" + combined
    )
    assert "getattr_tautology" in combined or "cheat-signature" in combined
