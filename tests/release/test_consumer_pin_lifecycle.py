"""Release hooks update real consumer copies and keep dev installs publishable."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest
from scripts.consumer_install_pins import (
    INSTALL_PIN,
    RELEASE_DOCS,
    documented_release,
    pin_paths,
    plan_pin_updates,
)

from tests.ci.workflow_support import REPO_ROOT
from tests.docs.support import load_script_module
from tests.release.test_prepare_version_bump import _prepare_tree, _run_bump, _snapshot


def _assert_consumers(root: Path, expected: str, monkeypatch: pytest.MonkeyPatch) -> None:
    assert documented_release(root) == expected
    for path in pin_paths(root):
        text = path.read_text()
        assert set(INSTALL_PIN.findall(text)) == {expected}, path
        assert set(RELEASE_DOCS.findall(text)) == {expected}, path
    lock = json.loads((root / "skills-lock.json").read_text())
    for entry in lock["skills"].values():
        if entry.get("source") == "alexhawat/mergeCraft":
            assert (
                entry["computedHash"]
                == hashlib.sha256((root / entry["skillPath"]).read_bytes()).hexdigest()
            )

    bundle = load_script_module("scripts/gen_llms_full.py")
    monkeypatch.setattr(bundle, "REPO_ROOT", root)
    assert (root / "llms-full.txt").read_text() == bundle._render_llms_full()
    skills = load_script_module("scripts/gen_agent_packages.py")
    monkeypatch.setattr(skills, "REPO_ROOT", root)
    monkeypatch.setattr(skills, "SOURCE_SKILL", root / "skills/mergecraft/SKILL.md")
    monkeypatch.setattr(skills, "HARNESS_MANIFEST", root / "skills/harnesses.yaml")
    monkeypatch.delenv("MERGECRAFT_AGENT_PACKAGES_REF", raising=False)
    for harness, generated in skills.render_all().items():
        assert (root / "skills" / harness / "mergecraft/SKILL.md").read_text() == generated


def test_prepare_publish_dev_and_next_release_keep_consumer_versions_coherent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _prepare_tree(tmp_path)
    first = _run_bump(root, documented_release(root), "9.9.9a9")
    assert first.returncode == 0, first.stderr
    _assert_consumers(root, "9.9.9a9", monkeypatch)
    before = {path: path.read_bytes() for path in pin_paths(root)}
    shutil.copy2(REPO_ROOT / "scripts/post-release.sh", root / "scripts/post-release.sh")
    post = subprocess.run(
        ["bash", "scripts/post-release.sh", "", "9.9.9a9"], cwd=root, capture_output=True, text=True
    )
    assert post.returncode == 0, post.stderr
    assert 'version = "9.9.9a10.dev0"' in (root / "pyproject.toml").read_text()
    assert all(path.read_bytes() == content for path, content in before.items())
    assert plan_pin_updates(root, "9.9.9a10.dev0") == {}
    _assert_consumers(root, "9.9.9a9", monkeypatch)

    # The independent gate catches a version-only bump even with all old pins
    # internally consistent; the next real prepare repairs all consumer copies.
    assert plan_pin_updates(root, "9.9.9a10")
    second = _run_bump(root, "9.9.9a10.dev0", "9.9.9a10")
    assert second.returncode == 0, second.stderr
    assert plan_pin_updates(root, "9.9.9a10") == {}
    _assert_consumers(root, "9.9.9a10", monkeypatch)


@pytest.mark.parametrize("damage", ["stale-pin", "missing-surface", "missing-skill-lock"])
def test_consumer_input_errors_abort_before_any_version_file_changes(
    tmp_path: Path, damage: str
) -> None:
    root = _prepare_tree(tmp_path)
    path = root / "docs/mcp.md"
    if damage == "stale-pin":
        path.write_text(INSTALL_PIN.sub("mergecraft-action==0.0.1", path.read_text()))
    elif damage == "missing-surface":
        path.unlink()
    else:
        (root / "skills-lock.json").write_text('{"skills": {}}\n')
    before = _snapshot(root)
    failed = _run_bump(root, documented_release(root), "9.9.9a9")
    assert failed.returncode != 0
    assert _snapshot(root) == before
