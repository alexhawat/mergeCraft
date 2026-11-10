"""The docs index generator fails on a docs page the manifest does not list (W2.3-6)."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from tests.ci.workflow_support import REPO_ROOT
from tests.docs.support import load_script_module

if TYPE_CHECKING:
    import pytest

_SCRIPT = REPO_ROOT / "scripts" / "gen_docs_index.py"


def test_repository_has_no_orphan_docs_pages() -> None:
    module = load_script_module(_SCRIPT)
    pages = module._manifest_pages(module._load_manifest())
    assert module.find_orphans(pages) == []


def test_orphan_page_is_reported(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    module = load_script_module(_SCRIPT)
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "listed.md").write_text("# listed\n", encoding="utf-8")
    (tmp_path / "docs" / "orphan.md").write_text("# orphan\n", encoding="utf-8")
    (tmp_path / "docs" / "_partial.md").write_text("# partial\n", encoding="utf-8")
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)
    assert module.find_orphans([{"path": "docs/listed.md"}]) == ["docs/orphan.md"]


def test_main_exits_nonzero_for_an_orphan(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    module = load_script_module(_SCRIPT)
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "orphan.md").write_text("# orphan\n", encoding="utf-8")
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(module, "_load_manifest", lambda: {"pages": [{"path": "README.md"}]})
    assert module.main(["--check"]) == 1
    assert "docs/orphan.md" in capsys.readouterr().err
