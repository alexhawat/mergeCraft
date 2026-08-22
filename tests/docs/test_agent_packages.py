"""RV1.3 — per-harness agent packaging contracts (RED until RV3).

Pins ``skills/harnesses.yaml``, ``scripts/gen_agent_packages.py``, absolute URLs in
generated packages, README path anti-invention, and ``make agent-packages-check`` in
``CI_STEPS``.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests.ci.workflow_support import REPO_ROOT, read_text
from tests.docs.support import ci_steps, load_harness_manifest, load_script_module

HARNESS_MANIFEST = REPO_ROOT / "skills" / "harnesses.yaml"
GEN_SCRIPT = REPO_ROOT / "scripts" / "gen_agent_packages.py"
README = REPO_ROOT / "README.md"
SKILLS_ROOT = REPO_ROOT / "skills"

_GITHUB_BLOB_URL = re.compile(
    r"https://github\.com/alexhawat/mergeCraft/blob/[^/]+/([^\s\"')]+)",
    re.IGNORECASE,
)
_SKILL_PATH_RE = re.compile(
    r"(?:^|[\s`\"])(\.[a-z0-9./-]+(?:skills?/mergecraft/?|hermes skills install))",
    re.IGNORECASE,
)


def _readme_agent_region() -> str:
    text = read_text("README.md")
    match = re.search(
        r"^##\s+.*(?:For LLM\s*/\s*Agents|For AI coding agents)[^\n]*\n(.*?)(?=^## |\Z)",
        text,
        re.MULTILINE | re.IGNORECASE | re.DOTALL,
    )
    assert match, "README agent section missing"
    return match.group(1)


def test_every_declared_harness_has_a_package_or_fallback() -> None:
    manifest = load_harness_manifest()
    harnesses = manifest.get("harnesses") or []
    assert isinstance(harnesses, list)
    assert harnesses, "skills/harnesses.yaml needs harnesses:"
    missing: list[str] = []
    for row in harnesses:
        if not isinstance(row, dict):
            continue
        harness_id = row.get("id")
        if not isinstance(harness_id, str):
            continue
        fallback = row.get("fallback")
        package_dir = SKILLS_ROOT / harness_id
        if fallback == "agents-md":
            continue
        if not package_dir.is_dir():
            missing.append(harness_id)
    assert not missing, f"harnesses without package or agents-md fallback: {missing}"


def test_packages_match_generator(tmp_path: Path) -> None:
    module = load_script_module(GEN_SCRIPT)
    assert module.main(["--check"]) == 0

    target = SKILLS_ROOT / "mergecraft" / "SKILL.md"
    if not target.is_file():
        pytest.skip("skills/mergecraft/SKILL.md missing — cannot inject drift")
    scratch_skill = tmp_path / "SKILL.md"
    scratch_skill.write_text(target.read_text(encoding="utf-8"), encoding="utf-8")
    original_skill_path = module.SOURCE_SKILL
    module.SOURCE_SKILL = scratch_skill
    try:
        scratch_skill.write_text(
            scratch_skill.read_text(encoding="utf-8") + "\n<!-- rv1 drift probe -->\n",
            encoding="utf-8",
        )
        exit_code = module.main(["--check"])
    finally:
        module.SOURCE_SKILL = original_skill_path
    assert exit_code != 0, "gen_agent_packages.py --check must fail after package drift"


def test_generated_packages_have_no_broken_relative_links() -> None:
    generated_skills = [
        skill_md
        for skill_md in SKILLS_ROOT.rglob("SKILL.md")
        if skill_md.parent.name != "mergecraft" or skill_md.parent.parent != SKILLS_ROOT
    ]
    assert generated_skills, "expected per-harness generated SKILL.md packages (RV3)"
    broken: list[str] = []
    for skill_md in generated_skills:
        text = skill_md.read_text(encoding="utf-8")
        if "../../" in text:
            broken.append(f"{skill_md.relative_to(REPO_ROOT)}: relative ../../ link")
        for match in _GITHUB_BLOB_URL.finditer(text):
            rel = match.group(1)
            if not (REPO_ROOT / rel).is_file():
                broken.append(f"{skill_md.relative_to(REPO_ROOT)}: {rel}")
    assert not broken, "\n".join(broken)


def test_unverified_formats_are_marked() -> None:
    manifest = load_harness_manifest()
    harnesses = manifest.get("harnesses") or []
    offenders: list[str] = []
    for row in harnesses:
        if not isinstance(row, dict):
            continue
        harness_id = row.get("id")
        if not isinstance(harness_id, str):
            continue
        if row.get("source"):
            continue
        if row.get("fallback") != "agents-md":
            offenders.append(harness_id)
    assert not offenders, (
        f"harness rows without source: must set fallback: agents-md (D3): {offenders}"
    )


def test_readme_paths_match_harness_manifest() -> None:
    manifest = load_harness_manifest()
    declared_paths: set[str] = set()
    for block in manifest.get("install_paths") or []:
        if isinstance(block, dict) and isinstance(block.get("path"), str):
            declared_paths.add(block["path"].rstrip("/"))
        if isinstance(block, dict):
            for alt in block.get("alt_paths") or []:
                if isinstance(alt, str):
                    declared_paths.add(alt.rstrip("/"))
    for row in manifest.get("harnesses") or []:
        if isinstance(row, dict):
            for alt in row.get("alt_paths") or []:
                if isinstance(alt, str):
                    declared_paths.add(alt.rstrip("/"))

    region = _readme_agent_region()
    readme_paths = {
        m.group(1).rstrip("/")
        for m in _SKILL_PATH_RE.finditer(region)
        if "/" in m.group(1) or m.group(1).startswith(".")
    }
    invented = sorted(path for path in readme_paths if path not in declared_paths)
    assert not invented, (
        f"README agent section names skill paths absent from skills/harnesses.yaml: {invented}"
    )


def test_make_agent_packages_check_in_ci_steps() -> None:
    steps = ci_steps()
    assert "agent-packages-check" in steps, (
        "Makefile CI_STEPS must include agent-packages-check (RV3)"
    )
