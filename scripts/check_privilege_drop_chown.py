#!/usr/bin/env python3
"""Guard: privileged-write functions must chown before the privilege drop.

mergeCraft shipped the same bug shape twice against itself: a still-root
function creates a directory (``some_dir.mkdir(...)``) and writes files into
it, but the ``setpriv``-dropped agent CLI subprocess needs to read or write
that same directory afterward. Ownership follows the *creating* process's
uid, not the parent directory's owner, so a plain ``mkdir()`` with no chown
leaves the path root-owned and the dropped-privilege process fails with
``EACCES``/``Permission denied`` (``$HOME`` after ``setpriv``'s uid/gid drop,
then ``$CODEX_HOME``/``.gemini``/``.claude`` — see W3.4 / #190 / #194).

This is a narrow, repo-local, AST-based check — deliberately not a general
product-wide pattern-scanner rule in ``semgrep-default-rules.yml``. That
ruleset ships to every repo mergeCraft reviews; ``prepare_workspace_for_agent``
is a mergeCraft-specific symbol no consumer repo will ever define, so a
generic "mkdir without a paired chown" rule there would either never fire
(named-helper form) or false-positive constantly (any looser form — most
directories anywhere have no reason to be chowned). It also cannot express
*ordering* (chown strictly after the write) without much more machinery, and
is intentionally scoped to functions that both create a directory AND write
a file into it — a mkdir with no write (e.g.
``codex.py::_safe_codex_home_parent`` locating a safe parent directory
nobody writes into directly) is not this bug shape, and flagging it would be
a false positive. A function is considered "handled" if it calls
``prepare_workspace_for_agent(...)`` (the existing chown helper) or performs
any explicit ``chown`` call anywhere in its body — including a deliberate
root-only lock (see ``git_setup.py::write_askpass_script``, which
``os.chown``s the askpass secret to root *on purpose*); this check verifies
ownership was **considered**, not that it was resolved a particular way.

Module: scripts.check_privilege_drop_chown
Depends: ast, pathlib, sys

Exports:
    main — CLI entry; scans the scoped files for mkdir-without-chown
        functions and reports each as ``file:line: function()``.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# Deliberately narrow: the three agent drivers that write a provider-home-like
# directory (``$CODEX_HOME``, ``.gemini``, ``.claude``) a setpriv-dropped agent
# CLI subprocess reads/writes afterward, plus the privilege-drop helpers
# themselves — not every module under ``src/mergecraft/agents/`` that happens
# to call ``.mkdir()``. A first pass scanned the whole ``agents/`` package and
# false-positived on ``verifier.py::record_withdrawn_finding`` — it creates
# and writes ``.mergecraft/learnings.md`` inside the *checkout* workspace,
# which ``main.py`` already chowns whole via ``prepare_workspace_for_agent``
# before any driver runs; no privilege boundary is crossed there, so nothing
# to flag. Widening this list back out would need to first teach the check to
# tell "writes into a run-tmpdir-rooted provider home" apart from "writes
# into the already-agent-owned checkout workspace" — real dataflow, not a
# mechanical AST shape — so the list stays an explicit, reviewed set instead.
_SCOPED_FILES: tuple[Path, ...] = (
    REPO / "src" / "mergecraft" / "agents" / "claude.py",
    REPO / "src" / "mergecraft" / "agents" / "codex.py",
    REPO / "src" / "mergecraft" / "agents" / "gemini.py",
    REPO / "src" / "mergecraft" / "utils" / "privilege.py",
    REPO / "src" / "mergecraft" / "utils" / "git_setup.py",
)

_WRITE_ATTRS = frozenset({"write_text", "write_bytes", "write"})
_CHOWN_HELPER = "prepare_workspace_for_agent"


def _rel(path: Path) -> str:
    """Return repo-relative posix path for ``path``."""
    try:
        return path.resolve().relative_to(REPO).as_posix()
    except ValueError:
        return path.as_posix()


def _call_attr_name(node: ast.AST) -> str | None:
    """Return the attribute name of a ``$X.<attr>(...)`` call, else ``None``."""
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


def _call_bare_name(node: ast.AST) -> str | None:
    """Return the function name of a bare ``<name>(...)`` call, else ``None``."""
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        return node.func.id
    return None


def _is_chown_evidence(node: ast.AST) -> bool:
    """True when ``node`` is a call that addresses ownership one way or another.

    Accepts the shared helper (``prepare_workspace_for_agent``), a direct
    ``os.chown``/``Path.chown`` call, or a ``subprocess`` invocation whose
    argv contains the literal ``"chown"`` (how ``prepare_workspace_for_agent``
    itself shells out) — any of these means a human already made a decision
    about ownership here, which is what this check exists to require.
    """
    if _call_bare_name(node) == _CHOWN_HELPER:
        return True
    if _call_attr_name(node) == "chown":
        return True
    if isinstance(node, ast.Call):
        for arg in node.args:
            if isinstance(arg, ast.List):
                for elt in arg.elts:
                    if isinstance(elt, ast.Constant) and elt.value == "chown":
                        return True
    return False


def _function_violation(func: ast.FunctionDef | ast.AsyncFunctionDef) -> int | None:
    """Return the line of the first offending ``mkdir()`` call, or ``None``.

    Flags a function only when it both creates a directory and writes a file
    into it (see module docstring for why the write requirement matters) and
    has no chown evidence anywhere in its body.
    """
    mkdir_line: int | None = None
    has_write = False
    has_chown = False
    for node in ast.walk(func):
        if node is func:
            continue
        if _is_chown_evidence(node):
            has_chown = True
        attr = _call_attr_name(node)
        if attr == "mkdir" and mkdir_line is None:
            mkdir_line = node.lineno  # type: ignore[union-attr]
        elif attr in _WRITE_ATTRS:
            has_write = True
    if mkdir_line is not None and has_write and not has_chown:
        return mkdir_line
    return None


def _scan_file(path: Path) -> list[str]:
    """Scan ``path`` for mkdir-without-chown functions, with a file-wide escape hatch.

    mergeCraft's real fix shape (``codex.py::_build_env``, W3.4 / #194) centralizes
    the chown call in the *caller*, once, after it invokes ``_setup_codex_auth()``
    and ``write_mcp_config()`` — both of which mkdir+write but never chown
    themselves. A purely per-function check false-positives on exactly this,
    correct, shape. So a function is only reported when the *whole file* has no
    chown evidence anywhere — if evidence exists somewhere else in the file, the
    caller is trusted to have paired it with this function's write. This trades
    away precision within a file that mixes multiple unrelated privileged-write
    concerns (an unrelated, genuinely-unchowned mkdir could hide behind another
    function's legitimate chown) — not a risk today since every scoped file
    handles exactly one provider-home directory, but worth knowing if that
    changes. Ordering (chown strictly after the write) still isn't verified —
    same limitation as before, see the module docstring.
    """
    text = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError as exc:
        return [f"{_rel(path)}: could not parse ({exc})"]

    file_has_chown = any(_is_chown_evidence(node) for node in ast.walk(tree))

    violations: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        line = _function_violation(node)
        if line is not None and not file_has_chown:
            violations.append(f"{_rel(path)}:{line}: {node.name}()")
    return violations


def main() -> int:
    """Scan the scoped privilege-drop-adjacent files for unpaired mkdir calls."""
    violations: list[str] = []
    for path in _SCOPED_FILES:
        if not path.is_file():
            continue
        violations.extend(_scan_file(path))

    if violations:
        print(
            "mkdir() with no paired prepare_workspace_for_agent()/chown in the "
            "same function — a privileged (root) write into a directory a "
            "setpriv-dropped agent subprocess must later use (W3.4 / #190 / #194):",
            file=sys.stderr,
        )
        for v in violations:
            print(f"  {v}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
