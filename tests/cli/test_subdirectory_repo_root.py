"""Commands run from a repository subdirectory act on the repository root (#1339).

An omitted ``--cwd`` (or ``--repo-root``) resolves to the git work-tree root of
the process working directory. An explicit ``--cwd`` is still taken literally.
"""

from __future__ import annotations

import re
import subprocess
from typing import TYPE_CHECKING

import pytest
import yaml
from typer.testing import CliRunner

from mergecraft.cli.app import app

if TYPE_CHECKING:
    from pathlib import Path

_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_ENV = {"NO_COLOR": "1", "TERM": "dumb", "COLUMNS": "200"}


def _repo(tmp_path: Path) -> tuple[Path, Path]:
    """Create a git repo with a committed config and return ``(root, subdir)``."""
    root = tmp_path / "repo"
    sub = root / "src" / "pkg"
    sub.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    (root / ".mergecraft").mkdir()
    (root / ".mergecraft" / "config.yaml").write_text(
        "models:\n  - anthropic/claude-sonnet\n", encoding="utf-8"
    )
    for name in ("one.txt", "two.txt"):
        (root / name).write_text(f"{name}\n", encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=root, check=True)
        subprocess.run(
            [
                "git",
                "-c",
                "user.email=t@example.invalid",
                "-c",
                "user.name=T",
                "commit",
                "-qm",
                name,
            ],
            cwd=root,
            check=True,
        )
    return root.resolve(), sub


def _invoke(argv: list[str]) -> tuple[int, str]:
    """Run the CLI and return ``(exit_code, plain output)``."""
    result = CliRunner().invoke(app, argv, env=_ENV)
    return result.exit_code, _ANSI.sub("", result.stdout + result.stderr)


@pytest.fixture
def in_subdir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Chdir into ``src/pkg`` of a fresh repo and return the repo root."""
    monkeypatch.delenv("MERGECRAFT_CONFIG", raising=False)
    monkeypatch.delenv("MERGECRAFT_ENV", raising=False)
    root, sub = _repo(tmp_path)
    monkeypatch.chdir(sub)
    return root


def test_config_show_reads_the_root_config(in_subdir: Path) -> None:
    """``config show`` reports the committed value, not the defaults."""
    code, out = _invoke(["config", "show", "models"])
    assert code == 0, out
    assert "anthropic/claude-sonnet" in out, out


def test_config_set_writes_the_root_config(in_subdir: Path) -> None:
    """``config set`` edits the root config and creates no nested ``.mergecraft/``."""
    code, out = _invoke(["config", "set", "models", "foo/bar"])
    assert code == 0, out
    data = yaml.safe_load((in_subdir / ".mergecraft" / "config.yaml").read_text())
    assert data["models"] == ["foo/bar"]
    assert not (in_subdir / "src" / "pkg" / ".mergecraft").exists()


def test_provider_list_reads_the_root_registry(in_subdir: Path) -> None:
    """``provider list`` sees the providers registered at the root."""
    (in_subdir / ".mergecraft" / "config.yaml").write_text(
        "providers:\n  - label: acme\n    harness: opencode\n    url: https://acme.example\n",
        encoding="utf-8",
    )
    code, out = _invoke(["provider", "list"])
    assert code == 0, out
    assert "acme" in out, out
    assert "no providers registered" not in out


def test_plan_does_not_write_into_the_subdirectory(in_subdir: Path) -> None:
    """``plan`` resolves the root and leaves no stray ``.mergecraft/`` behind."""
    code, out = _invoke(["plan"])
    assert code == 0, out
    assert "anthropic/claude-sonnet" in out, out
    assert not (in_subdir / "src" / "pkg" / ".mergecraft").exists()


def test_init_scaffolds_the_root_workflow(in_subdir: Path) -> None:
    """``init`` writes the workflow GitHub runs, at the repository root."""
    code, out = _invoke(["init"])
    assert code == 0, out
    assert (in_subdir / ".github" / "workflows" / "mergecraft.yml").is_file()
    assert not (in_subdir / "src" / "pkg" / ".github").exists()
    assert not (in_subdir / "src" / "pkg" / ".mergecraft").exists()


def test_review_dry_run_finds_the_repository(in_subdir: Path) -> None:
    """``review --dry-run`` from a subdirectory does not report "not a git repository"."""
    code, out = _invoke(["review", "--dry-run"])
    assert "not a git repository" not in out, out
    assert code == 0, out


def test_explicit_cwd_is_taken_literally(in_subdir: Path) -> None:
    """An explicit ``--cwd`` names the directory the operator chose."""
    sub = in_subdir / "src" / "pkg"
    code, out = _invoke(["config", "show", "models", "--cwd", str(sub)])
    assert code == 0, out
    assert "anthropic/claude-sonnet" not in out, out
