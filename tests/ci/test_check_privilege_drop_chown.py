"""``scripts/check_privilege_drop_chown.py`` — the privilege-drop chown gate.

mergeCraft shipped the bug this script detects twice against itself (W3.4 /
#190 / #194): a still-root function creates a provider-home-like directory
and writes files into it, but a later ``setpriv``-dropped agent CLI
subprocess needs to write there too — and ownership follows the *creating*
process's uid, not a later chown on the parent. These tests exercise the
scanner directly (synthetic sources, both the shipped-bug shape and its fix)
rather than only the current tree, so a future edit that weakens detection
fails loudly here instead of only showing up as a silent gap in ``make lint``.
"""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path
from typing import TYPE_CHECKING, Any

from tests.ci.workflow_support import REPO_ROOT

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch


def _load_script() -> Any:
    path = REPO_ROOT / "scripts" / "check_privilege_drop_chown.py"
    assert path.is_file(), "scripts/check_privilege_drop_chown.py missing"
    spec = importlib.util.spec_from_file_location("check_privilege_drop_chown", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _first_function(source: str) -> ast.FunctionDef:
    tree = ast.parse(source)
    return next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef))


# ---------------------------------------------------------------------------
# The shipped-bug shape: mkdir + write, no chown anywhere — must be flagged.
# ---------------------------------------------------------------------------


def test_flags_mkdir_and_write_with_no_chown() -> None:
    module = _load_script()
    source = """
def write_mcp_config(ctx):
    config_dir = Path(ctx.tmpdir) / ".claude"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "mcp.json"
    config_path.write_text("{}")
    return str(config_path)
"""
    func = _first_function(source)
    line = module._function_violation(func)
    assert line == 4  # the mkdir() call's line


# ---------------------------------------------------------------------------
# The real fix shape: mkdir + write + prepare_workspace_for_agent — clean.
# ---------------------------------------------------------------------------


def test_does_not_flag_when_prepare_workspace_for_agent_is_called() -> None:
    module = _load_script()
    source = """
def write_mcp_config(ctx):
    config_dir = Path(ctx.tmpdir) / ".claude"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "mcp.json"
    config_path.write_text("{}")
    prepare_workspace_for_agent(str(config_dir))
    return str(config_path)
"""
    func = _first_function(source)
    assert module._function_violation(func) is None


def test_does_not_flag_an_explicit_chown_even_to_root() -> None:
    """A deliberate root-only lock (secrets) still counts as "considered"."""
    module = _load_script()
    source = """
def write_askpass_script(tmpdir, token):
    path = Path(tmpdir) / "credentials"
    path.mkdir(mode=0o700, exist_ok=True)
    if os.getuid() == 0:
        os.chown(path, 0, 0)
    askpass = path / "git-askpass.sh"
    askpass.write_text("...")
    return str(askpass)
"""
    func = _first_function(source)
    assert module._function_violation(func) is None


def test_does_not_flag_a_subprocess_chown_call() -> None:
    """``prepare_workspace_for_agent`` itself shells out to ``chown`` — not a
    method call, so it needs its own detection path."""
    module = _load_script()
    source = """
def prepare_workspace_for_agent(workspace):
    target = Path(workspace)
    target.mkdir(parents=True, exist_ok=True)
    (target / "marker").write_text("x")
    subprocess.run(["chown", "-R", "1000:1000", str(target)])
"""
    func = _first_function(source)
    assert module._function_violation(func) is None


# ---------------------------------------------------------------------------
# mkdir with no write is not this bug shape (e.g. locating a safe parent
# directory nobody writes into directly) — must not be flagged.
# ---------------------------------------------------------------------------


def test_does_not_flag_mkdir_with_no_write() -> None:
    module = _load_script()
    source = """
def _safe_codex_home_parent(ctx):
    cache = Path(ctx.tmpdir) / "cache"
    cache.mkdir(parents=True, exist_ok=True)
    return cache
"""
    func = _first_function(source)
    assert module._function_violation(func) is None


# ---------------------------------------------------------------------------
# Whole-file / whole-tree scans.
# ---------------------------------------------------------------------------


def test_does_not_flag_when_chown_is_in_a_different_caller_function(tmp_path: Path) -> None:
    """The real fix shape: helpers mkdir+write, the caller chowns once (W3.4 / #194).

    ``codex.py::_build_env`` calls ``_setup_codex_auth()`` and
    ``write_mcp_config()`` — both mkdir+write, neither chowns itself — then
    calls ``prepare_workspace_for_agent()`` once, after both have run. A
    per-function-only check false-positives on exactly this shape; the
    file-wide escape hatch in ``_scan_file`` must recognize it as handled.
    """
    module = _load_script()
    target = tmp_path / "codexlike.py"
    target.write_text(
        "def _setup_codex_auth(ctx, codex_home):\n"
        "    codex_home.mkdir(parents=True, exist_ok=True)\n"
        "    (codex_home / 'auth.json').write_text('{}')\n"
        "\n"
        "def write_mcp_config(ctx, codex_home):\n"
        "    codex_home.mkdir(parents=True, exist_ok=True)\n"
        "    (codex_home / 'config.toml').write_text('')\n"
        "\n"
        "def _build_env(ctx):\n"
        "    codex_home = _codex_home(ctx)\n"
        "    _setup_codex_auth(ctx, codex_home=codex_home)\n"
        "    prepare_workspace_for_agent(str(codex_home))\n"
        "    return {}\n",
        encoding="utf-8",
    )
    assert module._scan_file(target) == []


def test_scan_file_reports_relative_path_and_function_name(tmp_path: Path) -> None:
    module = _load_script()
    target = tmp_path / "broken.py"
    target.write_text(
        "def write_mcp_config(ctx):\n"
        "    d = Path(ctx.tmpdir) / '.claude'\n"
        "    d.mkdir(parents=True, exist_ok=True)\n"
        "    (d / 'mcp.json').write_text('{}')\n",
        encoding="utf-8",
    )
    violations = module._scan_file(target)
    assert len(violations) == 1
    assert "write_mcp_config()" in violations[0]


def test_current_tree_is_clean() -> None:
    """Regression pin: the real, currently-scoped files pass with zero findings.

    mergeCraft fixed this exact bug in ``claude.py``/``gemini.py``/``codex.py``
    (W3.4 / #190 / #194) by routing every provider-home write through
    ``prepare_workspace_for_agent`` as the last step. If this test starts
    failing, either the fix regressed or a new unpaired ``mkdir()`` landed in
    the scoped files — both are real findings, not scanner noise.
    """
    module = _load_script()
    violations: list[str] = []
    for path in module._SCOPED_FILES:
        if path.is_file():
            violations.extend(module._scan_file(path))
    assert violations == []


def test_main_exits_nonzero_when_scoped_files_have_a_violation(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """End-to-end proof the gate can fail: point ``main()`` at a broken copy."""
    module = _load_script()
    agents_dir = tmp_path / "src" / "mergecraft" / "agents"
    agents_dir.mkdir(parents=True)
    broken = agents_dir / "claude.py"
    broken.write_text(
        "def write_mcp_config(ctx):\n"
        "    d = Path(ctx.tmpdir) / '.claude'\n"
        "    d.mkdir(parents=True, exist_ok=True)\n"
        "    (d / 'mcp.json').write_text('{}')\n"
        "    return str(d)\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "_SCOPED_FILES", (broken,))
    assert module.main() == 1
