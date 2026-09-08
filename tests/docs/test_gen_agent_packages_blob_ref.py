"""Standalone skills use a documentation commit whose linked paths exist."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from tests.ci.workflow_support import REPO_ROOT
from tests.docs.support import load_script_module

GEN_SCRIPT = REPO_ROOT / "scripts" / "gen_agent_packages.py"


def test_blob_ref_uses_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    module = load_script_module(GEN_SCRIPT)
    monkeypatch.setenv("MERGECRAFT_AGENT_PACKAGES_REF", "verified-release")
    monkeypatch.setattr(module, "git_ref_exists", lambda *a, **kw: True)
    assert module._blob_ref() == "verified-release"


def test_blob_ref_independent_of_shallow_checkout(monkeypatch: pytest.MonkeyPatch) -> None:
    module = load_script_module(GEN_SCRIPT)
    monkeypatch.delenv("MERGECRAFT_AGENT_PACKAGES_REF", raising=False)
    expected = module.render_all()
    monkeypatch.setattr(module, "git_ref_exists", lambda *a, **kw: False)
    assert module._blob_ref() == module.DOCUMENTATION_REF
    assert module.render_all() == expected


def test_generated_package_links_exist_in_pinned_git_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_script_module(GEN_SCRIPT)
    monkeypatch.delenv("MERGECRAFT_AGENT_PACKAGES_REF", raising=False)
    fixture = json.loads(
        (Path(__file__).parent / "fixtures" / "agent_package_documentation.json").read_text()
    )
    assert fixture["ref"] == module.DOCUMENTATION_REF
    tree = fixture["blobs"]
    targets: set[str] = set()
    for index, (_, content) in enumerate(module.render_all().items()):
        copied = tmp_path / str(index) / "SKILL.md"
        copied.parent.mkdir()
        copied.write_text(content)
        text = copied.read_text()
        assert "(../../" not in text
        for ref, path in re.findall(
            r"https://github.com/alexhawat/mergeCraft/blob/([^/]+)/([^\s)#]+)", text
        ):
            assert ref == module.DOCUMENTATION_REF
            targets.add(path)
            assert path in tree
        assert "mergecraft provider auth" in text
    assert "docs/mcp.md" in targets


def test_unknown_explicit_documentation_ref_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    module = load_script_module(GEN_SCRIPT)
    monkeypatch.setenv("MERGECRAFT_AGENT_PACKAGES_REF", "missing-release")
    monkeypatch.setattr(module, "git_ref_exists", lambda *a, **kw: False)
    with pytest.raises(ValueError, match="fetch it"):
        module._blob_ref()
