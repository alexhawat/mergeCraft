"""G6 — pre-commit hook rev vs. pyproject.toml pin drift guard (G-F11).

``check_hook_pins.py`` was added with a happy-path proof only (a scratch
copy with a stale ``rev`` was shown to fail once, by hand, during the PR
that added it) — no regression coverage for the negative paths a reviewer
flagged: mismatched rev, a missing pyproject dev pin, and a missing
``.pre-commit-config.yaml`` hook entry. Without these, a change that made
the guard always pass would re-enable the exact silent drift G-F11 found.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import TYPE_CHECKING, Any

from tests.ci.workflow_support import REPO_ROOT

if TYPE_CHECKING:
    import pytest


def _load_check_hook_pins() -> Any:
    path = REPO_ROOT / "scripts" / "check_hook_pins.py"
    assert path.is_file(), "scripts/check_hook_pins.py missing"
    spec = importlib.util.spec_from_file_location("check_hook_pins", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_RUFF_REPO = "https://github.com/astral-sh/ruff-pre-commit"


def _pyproject_text(ruff_pin: str | None) -> str:
    dep_line = f'    "ruff=={ruff_pin}",\n' if ruff_pin is not None else ""
    return f"""\
[dependency-groups]
dev = [
{dep_line}    "mypy==1.20.2",
]
"""


_OTHER_HOOK = (
    "  - repo: https://github.com/pre-commit/pre-commit-hooks\n"
    "    rev: v9.9.9\n    hooks:\n      - id: check-yaml\n"
)


def _pre_commit_text(ruff_rev: str | None) -> str:
    """`ruff_rev=None` omits the ruff repo entirely but keeps an unrelated one,
    so the "missing entry" fixture matches a realistic config rather than an
    empty `repos:` (see test_hook_revs_handles_null_repos_key for that edge)."""
    repo_block = (
        f"  - repo: {_RUFF_REPO}\n    rev: {ruff_rev}\n    hooks:\n      - id: ruff\n"
        if ruff_rev is not None
        else _OTHER_HOOK
    )
    return f"repos:\n{repo_block}"


def _write_fixture(
    tmp_path: Path, module: Any, *, ruff_pin: str | None, ruff_rev: str | None
) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pre_commit = tmp_path / ".pre-commit-config.yaml"
    pyproject.write_text(_pyproject_text(ruff_pin), encoding="utf-8")
    pre_commit.write_text(_pre_commit_text(ruff_rev), encoding="utf-8")
    module.PYPROJECT = pyproject
    module.PRE_COMMIT_CONFIG = pre_commit


class TestDevDependencyPins:
    """Unit coverage for the pure `[dependency-groups].dev` parser."""

    def test_parses_exact_pins(self) -> None:
        module = _load_check_hook_pins()
        pins = module._dev_dependency_pins(_pyproject_text("0.16.2"))
        assert pins["ruff"] == "0.16.2"

    def test_ignores_non_pinned_entries(self) -> None:
        module = _load_check_hook_pins()
        text = '[dependency-groups]\ndev = [\n    "ruff>=0.16",\n    "mypy==1.20.2",\n]\n'
        pins = module._dev_dependency_pins(text)
        assert "ruff" not in pins
        assert pins["mypy"] == "1.20.2"


class TestHookRevs:
    """Unit coverage for the pure `.pre-commit-config.yaml` parser."""

    def test_parses_repo_revs(self) -> None:
        module = _load_check_hook_pins()
        revs = module._hook_revs(_pre_commit_text("v0.16.2"))
        assert revs[_RUFF_REPO] == "v0.16.2"

    def test_empty_repos_list_is_empty_dict(self) -> None:
        module = _load_check_hook_pins()
        assert module._hook_revs("repos: []\n") == {}

    def test_null_repos_key_is_empty_dict(self) -> None:
        """`repos:` with no items parses to `{"repos": None}` in YAML, not `[]` —
        a bare `.get("repos", [])` does not catch this since the key is present.
        Found while writing this suite; `scripts/check_hook_pins.py` now guards
        it with `data.get("repos") or []`."""
        module = _load_check_hook_pins()
        assert module._hook_revs("repos:\n") == {}


class TestMainDriftDetection:
    """Orchestration coverage — the negative paths flagged on PR #175."""

    def test_passes_when_rev_matches_pin(self, tmp_path: Path) -> None:
        module = _load_check_hook_pins()
        _write_fixture(tmp_path, module, ruff_pin="0.16.2", ruff_rev="v0.16.2")
        assert module.main() == 0

    def test_fails_on_mismatched_rev(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        module = _load_check_hook_pins()
        _write_fixture(tmp_path, module, ruff_pin="0.16.2", ruff_rev="v0.15.12")
        assert module.main() != 0
        err = capsys.readouterr().err
        assert "0.15.12" in err
        assert "0.16.2" in err

    def test_fails_on_missing_pyproject_pin(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        module = _load_check_hook_pins()
        _write_fixture(tmp_path, module, ruff_pin=None, ruff_rev="v0.16.2")
        assert module.main() != 0
        assert "no pyproject.toml dev pin" in capsys.readouterr().err

    def test_fails_on_missing_pre_commit_entry(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        module = _load_check_hook_pins()
        _write_fixture(tmp_path, module, ruff_pin="0.16.2", ruff_rev=None)
        assert module.main() != 0
        assert "no `.pre-commit-config.yaml` entry" in capsys.readouterr().err

    def test_fails_closed_when_pre_commit_config_missing(self, tmp_path: Path) -> None:
        module = _load_check_hook_pins()
        module.PYPROJECT = tmp_path / "pyproject.toml"
        module.PYPROJECT.write_text(_pyproject_text("0.16.2"), encoding="utf-8")
        module.PRE_COMMIT_CONFIG = tmp_path / "does-not-exist.yaml"
        assert module.main() != 0

    def test_fails_closed_when_pyproject_missing(self, tmp_path: Path) -> None:
        module = _load_check_hook_pins()
        module.PRE_COMMIT_CONFIG = tmp_path / ".pre-commit-config.yaml"
        module.PRE_COMMIT_CONFIG.write_text(_pre_commit_text("v0.16.2"), encoding="utf-8")
        module.PYPROJECT = tmp_path / "does-not-exist.toml"
        assert module.main() != 0

    def test_repo_untracked_hooks_have_no_effect(self, tmp_path: Path) -> None:
        """A drifted hook this script doesn't track (unlisted `dep_name`) must not fail the guard."""
        module = _load_check_hook_pins()
        pyproject = tmp_path / "pyproject.toml"
        pre_commit = tmp_path / ".pre-commit-config.yaml"
        pyproject.write_text(_pyproject_text("0.16.2"), encoding="utf-8")
        pre_commit.write_text(
            "repos:\n"
            f"  - repo: {_RUFF_REPO}\n    rev: v0.16.2\n    hooks:\n      - id: ruff\n"
            "  - repo: https://github.com/pre-commit/pre-commit-hooks\n"
            "    rev: v9.9.9\n    hooks:\n      - id: check-yaml\n",
            encoding="utf-8",
        )
        module.PYPROJECT = pyproject
        module.PRE_COMMIT_CONFIG = pre_commit
        assert module.main() == 0


__all__ = [
    "TestDevDependencyPins",
    "TestHookRevs",
    "TestMainDriftDetection",
]
