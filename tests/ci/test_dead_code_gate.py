"""Exercise the real pinned Vulture process and exact contract exceptions."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_CHECKER = _REPO / "scripts" / "check_dead_code.py"


def _scan(
    root: Path, source: str, *, symbols: tuple[str, ...] = ()
) -> subprocess.CompletedProcess[str]:
    src = root / "src"
    src.mkdir(exist_ok=True)
    (src / "contract.py").write_text(source, encoding="utf-8")
    allowlist = root / "allowlist.json"
    allowlist.write_text(
        json.dumps(
            [{"reason": "Serialized model field consumed by the framework", "symbols": symbols}]
        ),
        encoding="utf-8",
    )
    return subprocess.run(
        [sys.executable, str(_CHECKER), "--root", str(root), "--allowlist", str(allowlist)],
        cwd=_REPO,
        capture_output=True,
        text=True,
        check=False,
    )


def test_unused_private_function_fails_real_scanner(tmp_path: Path) -> None:
    result = _scan(
        tmp_path,
        "class Contract:\n    serialized_value = 41\n\nprint(Contract())\n"
        "def _injected_unused_probe():\n    return 41\n",
        symbols=("src/contract.py:variable:serialized_value",),
    )
    assert result.returncode == 3
    assert "unused function '_injected_unused_probe'" in result.stdout


def test_reviewed_serialized_field_is_allowed(tmp_path: Path) -> None:
    result = _scan(
        tmp_path,
        "class Contract:\n    serialized_value = 41\n\nprint(Contract())\n",
        symbols=("src/contract.py:variable:serialized_value",),
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_contract_allowlist_cannot_hide_same_name_in_another_file(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / "unused.py").write_text("serialized_value = 42\n", encoding="utf-8")
    result = _scan(
        tmp_path,
        "class Contract:\n    serialized_value = 41\n\nprint(Contract())\n",
        symbols=("src/contract.py:variable:serialized_value",),
    )
    assert result.returncode == 3
    assert "src/unused.py:1: unused variable 'serialized_value'" in result.stdout
    assert "src/contract.py:" not in result.stdout


def test_stale_contract_entry_fails(tmp_path: Path) -> None:
    result = _scan(tmp_path, "print('used')\n", symbols=("src/contract.py:variable:removed",))
    assert result.returncode == 2
    assert "stale allowlist entry: src/contract.py:variable:removed" in result.stdout


def test_scanner_syntax_error_is_preserved(tmp_path: Path) -> None:
    result = _scan(tmp_path, "def broken(:\n")
    assert result.returncode == 1
    assert "invalid syntax" in result.stdout + result.stderr
