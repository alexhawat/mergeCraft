"""Plan 26 H4 — tracked-markdown checker (decision 9).

Scans ``git ls-files '*.md'`` only. Never walks gitignored trees.
Fails on decision-id tokens, ``Wave plan:``, and ``.ignorelocal/waves/``
outside a small allowlist.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _ROOT / "scripts" / "check_tracked_markdown.py"
_ALLOWLIST = "docs/dev/changelog-archive.md"


def _load_checker() -> Any:
    assert _SCRIPT.is_file(), "scripts/check_tracked_markdown.py missing"
    spec = importlib.util.spec_from_file_location("check_tracked_markdown", _SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )


def _init_repo(repo: Path) -> None:
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "config", "user.email", "test@example.com")


def _commit_all(repo: Path, message: str) -> None:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)


def test_list_tracked_markdown_invokes_git_ls_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_checker()
    calls: list[list[str]] = []

    def _fake_run(cmd: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0, "README.md\ndocs/cli.md\n", "")

    monkeypatch.setattr(subprocess, "run", _fake_run)
    listed = module.list_tracked_markdown(tmp_path)
    assert any(cmd[:2] == ["git", "ls-files"] and "*.md" in cmd for cmd in calls)
    names = {Path(path).name for path in listed}
    assert names == {"README.md", "cli.md"}


def test_scan_flags_decision_id_wave_plan_and_ignorelocal_citation() -> None:
    module = _load_checker()
    text = (
        "## LLM judges are secondary evaluators (D14, #45)\n"
        "Wave plan: some-local-path\n"
        "See also the operator notes under the local waves tree.\n"
        "Citation: .ignorelocal/waves/example.md\n"
    )
    offenses = module.scan_markdown(text, relpath="docs/REVIEW-DOCTRINE.md")
    kinds = {getattr(item, "kind", None) or item[0] for item in offenses}
    joined = " ".join(str(item) for item in offenses)
    assert any("D14" in joined or kind in {"decision-id", "D"} for kind in kinds) or "D14" in joined
    assert "Wave plan:" in joined or any(kind in {"wave-plan", "Wave plan"} for kind in kinds)
    assert ".ignorelocal/waves/" in joined or any(
        kind in {"ignorelocal-waves", "ignorelocal"} for kind in kinds
    )


def test_scan_flags_wave_dot_tokens() -> None:
    """DoD — word-boundary W#.# is an offense, same family as D##."""
    module = _load_checker()
    text = "See W4.4 and W12.7 in the tracing notes.\n"
    offenses = module.scan_markdown(text, relpath="docs/TRACING.md")
    joined = " ".join(str(item) for item in offenses)
    assert "W4.4" in joined
    assert "W12.7" in joined


def test_main_fails_on_tracked_wave_dot_token(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    (tmp_path / "README.md").write_text("# Title W4.4\nAlso W12.7.\n", encoding="utf-8")
    _commit_all(tmp_path, "add readme")
    module = _load_checker()
    module.REPO = tmp_path
    assert module.main() != 0


def test_allowlisted_changelog_archive_is_not_an_offense() -> None:
    module = _load_checker()
    text = "Historical note (D14) and Wave plan: archived.\n"
    offenses = module.scan_markdown(text, relpath=_ALLOWLIST)
    assert offenses == []


def test_main_fails_on_tracked_decision_id(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    (tmp_path / "README.md").write_text("# Title (D14)\n", encoding="utf-8")
    _commit_all(tmp_path, "add readme")
    module = _load_checker()
    module.REPO = tmp_path
    assert module.main() != 0


def test_main_passes_on_clean_tracked_markdown(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    (tmp_path / "README.md").write_text("# Title\nPlain behaviour.\n", encoding="utf-8")
    _commit_all(tmp_path, "add clean readme")
    module = _load_checker()
    module.REPO = tmp_path
    assert module.main() == 0


def test_checker_never_walks_a_gitignored_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Decision 9 — gitignored trees are invisible, even when they carry banned tokens."""
    _init_repo(tmp_path)
    (tmp_path / "README.md").write_text("# Clean\n", encoding="utf-8")
    (tmp_path / ".gitignore").write_text(".ignorelocal/\n.claude/\nCLAUDE.md\n", encoding="utf-8")
    ignored = tmp_path / ".ignorelocal" / "waves"
    ignored.mkdir(parents=True)
    (ignored / "secret-plan.md").write_text(
        "Wave plan: .ignorelocal/waves/secret-plan.md\nDecision D99 lives here.\n",
        encoding="utf-8",
    )
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "notes.md").write_text("D1\n", encoding="utf-8")
    (tmp_path / "CLAUDE.md").write_text("D2\n", encoding="utf-8")
    _commit_all(tmp_path, "tracked readme only")

    walked: list[str] = []
    real_walk = os.walk

    def _guarded_walk(top: str | os.PathLike[str], *args: object, **kwargs: object) -> Any:
        walked.append(str(top))
        if ".ignorelocal" in Path(top).parts or ".claude" in Path(top).parts:
            pytest.fail(f"checker walked gitignored tree: {top}")
        return real_walk(top, *args, **kwargs)

    monkeypatch.setattr(os, "walk", _guarded_walk)
    module = _load_checker()
    module.REPO = tmp_path
    assert module.main() == 0
    assert not any(".ignorelocal" in path for path in walked)


def test_checker_reports_tracked_file_not_gitignored_twin(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "cli.md").write_text("Heading (D14)\n", encoding="utf-8")
    (tmp_path / ".gitignore").write_text(".ignorelocal/\n", encoding="utf-8")
    hidden = tmp_path / ".ignorelocal" / "waves"
    hidden.mkdir(parents=True)
    (hidden / "plan.md").write_text("D77 Wave plan: hidden\n", encoding="utf-8")
    _commit_all(tmp_path, "tracked doctrine")
    module = _load_checker()
    module.REPO = tmp_path
    assert module.main() != 0
    listed = [str(path) for path in module.list_tracked_markdown(tmp_path)]
    assert any(path.endswith(("docs/cli.md", "cli.md")) for path in listed)
    assert not any(".ignorelocal" in path for path in listed)
