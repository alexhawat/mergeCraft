"""W8 — typing-suppression ratchet (#275 / Batch I RED).

``scripts/check_type_ignores.py`` is the RED artifact: it exits 1 while
allowed-tree ``type: ignore`` / ``cast(`` sites lack a one-line reason.
W9 walks the allowed tree (D6 skipped). The live-tree cleanliness test
stays ``xfail(strict=False)`` until then.
"""

from __future__ import annotations

import importlib.util
import io
from pathlib import Path
from typing import Any

import pytest

from tests.ci.workflow_support import REPO_ROOT

_EM_DASH = "\u2014"


def _load_check_type_ignores() -> Any:
    path = REPO_ROOT / "scripts" / "check_type_ignores.py"
    assert path.is_file(), "scripts/check_type_ignores.py missing"
    spec = importlib.util.spec_from_file_location("check_type_ignores", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_src(tmp_path: Path, rel: str, text: str) -> None:
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_script_exists() -> None:
    assert (REPO_ROOT / "scripts" / "check_type_ignores.py").is_file()


def test_d6_paths_cover_plan_src_files() -> None:
    module = _load_check_type_ignores()
    expected = {
        "src/mergecraft/agents/_stream_consumer.py",
        "src/mergecraft/agents/codex.py",
        "src/mergecraft/agents/structured_handoff.py",
        "src/mergecraft/analyzers/adapters.py",
        "src/mergecraft/analyzers/parsers/osv_json.py",
        "src/mergecraft/analyzers/scope.py",
        "src/mergecraft/cli/auth_cmd.py",
        "src/mergecraft/cli/gha_cmd.py",
        "src/mergecraft/evals/live_run.py",
        "src/mergecraft/mcp/check_runs.py",
        "src/mergecraft/mcp/git.py",
        "src/mergecraft/mcp/labels.py",
        "src/mergecraft/mcp/server.py",
        "src/mergecraft/mcp/upload.py",
        "src/mergecraft/mcp/verdict.py",
    }
    assert expected <= set(module.D6_SRC_PATHS)


@pytest.mark.parametrize(
    ("rel_path", "d6"),
    [
        ("src/mergecraft/agents/_stream_consumer.py", True),
        ("src/mergecraft/mcp/verdict.py", True),
        (r"src\mergecraft\mcp\verdict.py", True),
        ("src/mergecraft/utils/activity.py", False),
        ("src/mergecraft/evidence/emit.py", False),
    ],
)
def test_is_d6_src(rel_path: str, d6: bool) -> None:
    module = _load_check_type_ignores()
    assert module.is_d6_src(rel_path) is d6


@pytest.mark.parametrize(
    ("line", "ok"),
    [
        (f"x = 1  # type: ignore[arg-type] {_EM_DASH} int vs str at the call", True),
        ("x = 1  # type: ignore[arg-type]", False),
        ("x = 1  # type: ignore", False),
        (f"x = 1  # type: ignore[] {_EM_DASH} empty brackets", False),
        ("x = 1  # type: ignore[arg-type] - hyphen is not an em dash", False),
        ("x = 1  # type: ignore[arg-type] \u2013 en dash is not an em dash", False),
        (f"x = 1  # type: ignore[arg-type] {_EM_DASH}", False),
        (f"x = 1  # type: ignore[arg-type, misc] {_EM_DASH} two codes", True),
        (f"x = 1  # type:ignore[arg-type] {_EM_DASH} compact form", True),
        (f"x = 1  # type: ignore[arg-type] {_EM_DASH} café 原因", True),
    ],
)
def test_type_ignore_reason_rule(tmp_path: Path, line: str, ok: bool) -> None:
    module = _load_check_type_ignores()
    _write_src(tmp_path, "src/mergecraft/mod.py", f"{line}\n")
    inventory = module.scan_tree(tmp_path)
    assert inventory.ignore_count == 1
    assert inventory.cast_count == 0
    assert (inventory.allowed_count == 0) is ok
    if not ok:
        assert inventory.allowed_violations[0].kind == "ignore"


@pytest.mark.parametrize(
    ("text", "ok", "cast_sites"),
    [
        ("return cast(int, x)  # parsed JSON is a dict\n", True, 1),
        ("# cache hit is already typed\nreturn cast(int, x)\n", True, 1),
        ("return cast(int, x)\n", False, 1),
        ("#\nreturn cast(int, x)\n", False, 1),
        ("from typing import cast\n", True, 0),
        ("# return cast(int, x)\n", True, 0),
        ("# reason lives two lines up\n\nreturn cast(int, x)\n", False, 1),
        ('return cast("dict[str, object]", parsed)  # runtime JSON object\n', True, 1),
    ],
)
def test_cast_reason_rule(tmp_path: Path, text: str, ok: bool, cast_sites: int) -> None:
    module = _load_check_type_ignores()
    _write_src(tmp_path, "src/mergecraft/mod.py", text)
    inventory = module.scan_tree(tmp_path)
    assert inventory.cast_count == cast_sites
    assert (inventory.allowed_count == 0) is ok
    if not ok:
        assert inventory.allowed_violations[0].kind == "cast"
        assert inventory.allowed_violations[0].detail == "missing # reason"


def test_d6_file_without_reason_is_excluded_from_fail(tmp_path: Path) -> None:
    module = _load_check_type_ignores()
    _write_src(
        tmp_path,
        "src/mergecraft/mcp/verdict.py",
        "introduced = cast(int, raw)\ntrust_tier=trust,  # type: ignore[arg-type]\n",
    )
    _write_src(
        tmp_path,
        "src/mergecraft/utils/ok.py",
        f"x = 1  # type: ignore[misc] {_EM_DASH} FieldInfo subclass\n",
    )
    inventory = module.scan_tree(tmp_path)
    assert inventory.ignore_count == 2
    assert inventory.cast_count == 1
    assert inventory.d6_ignore_count == 1
    assert inventory.d6_cast_count == 1
    assert inventory.d6_count == 2
    assert inventory.allowed_count == 0
    buf = io.StringIO()
    assert module.check_type_ignores(inventory, stream=buf) == 0
    assert "type-ignore-check OK" in buf.getvalue()


def test_allowed_tree_missing_reason_fails(tmp_path: Path) -> None:
    module = _load_check_type_ignores()
    _write_src(
        tmp_path,
        "src/mergecraft/utils/activity.py",
        "sys.stdout.write = _on_write(original)  # type: ignore[method-assign]\n",
    )
    inventory = module.scan_tree(tmp_path)
    buf = io.StringIO()
    rc = module.check_type_ignores(inventory, stream=buf)
    assert rc == 1
    text = buf.getvalue()
    assert "type-ignore-check FAILED" in text
    assert "1 allowed-tree unjustified" in text
    assert "src/mergecraft/utils/activity.py:1 ignore" in text


def test_empty_tree_is_zero(tmp_path: Path) -> None:
    module = _load_check_type_ignores()
    (tmp_path / "src" / "mergecraft").mkdir(parents=True)
    inventory = module.scan_tree(tmp_path)
    assert inventory.ignore_count == 0
    assert inventory.cast_count == 0
    assert inventory.allowed_count == 0
    buf = io.StringIO()
    assert module.check_type_ignores(inventory, stream=buf) == 0


def test_missing_src_tree_exits_two(tmp_path: Path) -> None:
    module = _load_check_type_ignores()
    assert module.main(["--repo-root", str(tmp_path)]) == 2


def test_main_exits_one_on_allowed_unjustified(tmp_path: Path) -> None:
    module = _load_check_type_ignores()
    _write_src(tmp_path, "src/mergecraft/mod.py", "return cast(int, x)\n")
    assert module.main(["--repo-root", str(tmp_path)]) == 1


def test_main_exits_zero_when_justified(tmp_path: Path) -> None:
    module = _load_check_type_ignores()
    _write_src(
        tmp_path,
        "src/mergecraft/mod.py",
        f"x = 1  # type: ignore[arg-type] {_EM_DASH} helper is a Protocol\n"
        "return cast(int, x)  # JSON number\n",
    )
    assert module.main(["--repo-root", str(tmp_path)]) == 0


def test_scan_tree_skips_d6_from_allowed_on_live_src() -> None:
    module = _load_check_type_ignores()
    inventory = module.scan_tree(REPO_ROOT)
    for item in inventory.allowed_violations:
        assert not module.is_d6_src(item.path), item
    assert inventory.ignore_count >= inventory.d6_ignore_count
    assert inventory.cast_count >= inventory.d6_cast_count


def test_allowed_tree_ignores_and_casts_have_reasons() -> None:
    """Live ``src/mergecraft/`` (D6 excluded) must have a reason on every site."""
    module = _load_check_type_ignores()
    inventory = module.scan_tree(REPO_ROOT)
    buf = io.StringIO()
    assert module.check_type_ignores(inventory, stream=buf) == 0, buf.getvalue()
