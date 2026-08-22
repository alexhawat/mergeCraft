"""RD4.1 — docs pin consistency, ``llms-full`` generator, link gate, template headers.

Pins release-readiness version checks (D11), the unpinned consumer install form,
``scripts/gen_llms_full.py`` / ``llms-full.txt``, manifest + surface link
resolution, satellite README template headers, and Makefile ``llms-check`` wiring.
Implementation lands in RD4.2.
"""

from __future__ import annotations

import re
import subprocess
import tomllib
from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.ci.workflow_support import REPO_ROOT, read_text
from tests.docs.support import (
    action_uses_pattern,
    ci_steps,
    load_script_module,
    makefile_prerequisite_tokens,
)

README = REPO_ROOT / "README.md"
AGENTS_MD = REPO_ROOT / "AGENTS.md"
SKILL_MD = REPO_ROOT / "skills" / "mergecraft" / "SKILL.md"
INSTALL_DOC = REPO_ROOT / "docs" / "install.md"
LLMS_TXT = REPO_ROOT / "llms.txt"
LLMS_FULL = REPO_ROOT / "llms-full.txt"
MANIFEST = REPO_ROOT / "docs" / "manifest.yaml"
GEN_LLMS_FULL = REPO_ROOT / "scripts" / "gen_llms_full.py"
PYPROJECT = REPO_ROOT / "pyproject.toml"

_UNPINNED_INSTALL = 'uv tool install "merge-craft @ git+https://github.com/alexhawat/mergeCraft"'
_PIN_SCAN_PATHS = (README, AGENTS_MD, SKILL_MD, INSTALL_DOC, LLMS_TXT)
_LINK_SURFACE_PATHS = (README, AGENTS_MD, SKILL_MD, LLMS_TXT)

_PEP440_SUFFIX = r"(?:a\d+|b\d+|rc\d+|\.dev\d+)?"
_VERSION_TAG = re.compile(
    rf"@v(\d+\.\d+\.\d+{_PEP440_SUFFIX})\b",
    re.IGNORECASE,
)
_VERSIONED_GIT_REF = re.compile(
    r"git\+https://github\.com/alexhawat/mergeCraft@([^\s\"')]+)",
    re.IGNORECASE,
)
_PINNED_GIT_INSTALL = re.compile(
    r"git\+https://github\.com/alexhawat/mergeCraft@v",
    re.IGNORECASE,
)

_SATELLITE_READMES = (
    REPO_ROOT / "evals" / "README.md",
    REPO_ROOT / "assets" / "brand" / "README.md",
    REPO_ROOT / "docs" / "assets" / "README.md",
    REPO_ROOT / "CONTRIBUTING.md",
)

_EVAL_SCORE_TERMS = re.compile(
    r"\b(?:precision|recall|F1)\b",
    re.IGNORECASE,
)
_BENCHMARK_NUMBER = re.compile(
    r"(?:\b\d+(?:\.\d+)?%|\b\d+\.\d+\b|\b\d+\s*/\s*\d+\b)",
)

_LLMS_FULL_HEADER = re.compile(r"^===== FILE: (.+?) =====$", re.MULTILINE)


def _read(path: Path) -> str:
    assert path.is_file(), f"missing {path.relative_to(REPO_ROOT)} (RD4.2)"
    return path.read_text(encoding="utf-8")


def _pyproject_version() -> str:
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    version = data.get("project", {}).get("version")
    assert isinstance(version, str), "pyproject.toml missing project.version"
    assert version.strip(), "pyproject.toml missing project.version"
    return version


def _git_tags() -> list[str]:
    proc = subprocess.run(
        ["git", "tag", "--list"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, "git tag --list failed"
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def _collect_version_tag_refs(text: str) -> list[str]:
    refs: list[str] = []
    for match in _VERSION_TAG.finditer(text):
        refs.append(f"v{match.group(1)}")
    for pattern in (_VERSIONED_GIT_REF, action_uses_pattern):
        for match in pattern.finditer(text):
            ref = match.group(1).rstrip("#").strip()
            version_match = _VERSION_TAG.search(f"@{ref}")
            if version_match is not None:
                refs.append(f"v{version_match.group(1)}")
    return refs


def _markdown_links(text: str) -> set[str]:
    links: set[str] = set()
    for match in re.finditer(r"\]\(([^)]+)\)", text):
        target = match.group(1).strip()
        if not target or target.startswith(("http://", "https://", "#", "mailto:")):
            continue
        links.add(target.split("#", 1)[0])
    return links


def _resolve_link(source: Path, target: str) -> Path:
    return (source.parent / target).resolve()


def _load_manifest() -> dict[str, Any]:
    assert MANIFEST.is_file(), f"missing {MANIFEST.relative_to(REPO_ROOT)} (RD1.2)"
    data = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    assert isinstance(data, dict), "docs/manifest.yaml must parse as a mapping"
    return data


def _manifest_paths(manifest: dict[str, Any]) -> list[str]:
    pages = manifest.get("pages")
    assert isinstance(pages, list), "docs/manifest.yaml must define a pages: list"
    paths: list[str] = []
    for row in pages:
        assert isinstance(row, dict), "each manifest row must be a mapping"
        path = row.get("path")
        assert isinstance(path, str), "each manifest row needs path: str"
        assert path.strip(), "each manifest row needs path: str"
        paths.append(path)
    return paths


def test_install_pin_is_consistent_when_present() -> None:
    """D11 release-readiness gate: any ``@v…`` pin must match pyproject + an existing tag."""
    expected_tag = f"v{_pyproject_version()}"
    tags = _git_tags()
    tags_available = bool(tags)

    mismatches: list[str] = []
    missing_tags: list[str] = []

    for path in _PIN_SCAN_PATHS:
        text = _read(path)
        for ref in _collect_version_tag_refs(text):
            if ref != expected_tag:
                mismatches.append(f"{path.relative_to(REPO_ROOT)}: {ref!r} != {expected_tag!r}")
            elif tags_available and ref not in tags:
                missing_tags.append(f"{path.relative_to(REPO_ROOT)}: {ref!r} not in git tag --list")

    assert not mismatches, "version pins must equal pyproject.toml @v{version}:\n" + "\n".join(
        mismatches
    )

    if missing_tags:
        if not tags_available:
            pytest.skip(
                "git tag --list is empty (shallow clone?) — skipped tag-existence half of pin gate"
            )
        if all("v0.1.0a1" in item for item in missing_tags):
            pytest.xfail(
                "G1: v0.1.0a1 tag not cut yet — pin must resolve locally when tags exist (D8)"
            )
        pytest.fail(
            "version pins name tags that are not present locally:\n" + "\n".join(missing_tags)
        )


def test_unpinned_install_line_is_the_documented_form() -> None:
    """D11: consumer install stays unpinned; no ``git+…@v…`` variant in agent surfaces."""
    surfaces = (
        ("README.md", _read(README)),
        ("AGENTS.md", _read(AGENTS_MD)),
        ("skills/mergecraft/SKILL.md", _read(SKILL_MD)),
    )
    missing_unpinned = [label for label, text in surfaces if _UNPINNED_INSTALL not in text]
    assert not missing_unpinned, (
        f"consumer surfaces must teach the unpinned uv tool install form (D11): {missing_unpinned}"
    )

    pinned_installs = [
        f"{label}: {match.group(0)}"
        for label, text in surfaces
        for match in _PINNED_GIT_INSTALL.finditer(text)
    ]
    assert not pinned_installs, (
        "consumer install must not pin git+…@v… in README/AGENTS/skill (D11):\n"
        + "\n".join(pinned_installs)
    )


def test_llms_full_matches_generator(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """``scripts/gen_llms_full.py --check`` exits 0; a scratch mutation fails."""
    module = load_script_module(GEN_LLMS_FULL)
    output_path = tmp_path / "llms-full.txt"
    assert hasattr(module, "main"), "gen_llms_full.py must expose main(argv) -> int"

    if hasattr(module, "OUTPUT_PATH"):
        module.OUTPUT_PATH = output_path  # type: ignore[attr-defined]

    write_exit = module.main([])
    assert write_exit == 0, "default (write) mode must exit 0"

    check_exit = module.main(["--check"])
    assert check_exit == 0, "--check must exit 0 immediately after a write pass"

    generated = output_path.read_text(encoding="utf-8")
    mutated = generated.replace(
        "===== FILE: README.md =====",
        "===== FILE: README.md =====\n<!-- drift injected by test_llms_full_matches_generator -->",
        1,
    )
    assert mutated != generated, "llms-full header marker missing; cannot inject drift"
    output_path.write_text(mutated, encoding="utf-8")

    capsys.readouterr()
    drift_exit = module.main(["--check"])
    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert drift_exit != 0, "--check must exit non-zero when llms-full.txt drifts"
    assert any(line.startswith(("---", "+++", "@@")) for line in output.splitlines()), (
        "--check must emit a unified diff on llms-full drift; got:\n" + output
    )


def test_llms_full_includes_agents_and_readme() -> None:
    """``llms-full.txt`` concatenates README and AGENTS with file headers."""
    text = _read(LLMS_FULL)
    headers = _LLMS_FULL_HEADER.findall(text)
    assert "README.md" in headers, "llms-full.txt must include a README.md section header"
    assert "AGENTS.md" in headers, "llms-full.txt must include an AGENTS.md section header"

    readme_excerpt = _read(README).splitlines()[0].strip()
    agents_excerpt = _read(AGENTS_MD).splitlines()[0].strip()
    assert readme_excerpt in text, "llms-full.txt must embed README.md body content"
    assert agents_excerpt in text, "llms-full.txt must embed AGENTS.md body content"


def test_manifest_see_also_links_resolve() -> None:
    """Manifest rows exist on disk; surface markdown links resolve from their source file."""
    manifest = _load_manifest()
    missing_manifest = sorted(
        path for path in _manifest_paths(manifest) if not (REPO_ROOT / path).exists()
    )
    assert not missing_manifest, f"docs/manifest.yaml lists missing paths: {missing_manifest}"

    broken: list[str] = []
    for source in _LINK_SURFACE_PATHS:
        text = _read(source)
        for target in sorted(_markdown_links(text)):
            resolved = _resolve_link(source, target)
            if not resolved.exists():
                broken.append(f"{source.relative_to(REPO_ROOT)} -> {target!r}")
    assert not broken, "surface doc links must resolve:\n" + "\n".join(broken)


def test_satellite_readmes_have_purpose_line() -> None:
    """Satellite/contributor READMEs carry a template purpose line in the first 20 lines."""
    missing: list[str] = []
    for path in _SATELLITE_READMES:
        lines = _read(path).splitlines()[:20]
        region = "\n".join(lines)
        has_audience = "**Audience:**" in region
        has_purpose_sentence = any(
            line.strip()
            and not line.startswith("#")
            and not line.startswith("**Audience:**")
            and not line.startswith("|")
            and line.strip().endswith(".")
            and 20 <= len(line.strip()) <= 220
            for line in lines[1:]
        )
        if not (has_audience and has_purpose_sentence):
            missing.append(str(path.relative_to(REPO_ROOT)))
    assert not missing, (
        f"satellite READMEs need template headers (purpose + Audience) in first 20 lines: {missing}"
    )


def test_llms_check_and_docs_check_in_ci_steps() -> None:
    """Makefile exposes ``llms-check`` and folds it into ``docs-check`` / ``CI_STEPS``."""
    makefile = read_text("Makefile")
    assert re.search(r"^llms-check:", makefile, re.MULTILINE), (
        "Makefile must define an llms-check target (RD4.2)"
    )

    ci_steps_set = set(ci_steps())
    docs_check_deps = makefile_prerequisite_tokens(makefile, "docs-check")

    assert "llms-check" in ci_steps_set or "llms-check" in docs_check_deps, (
        "llms-check must be in CI_STEPS or docs-check prerequisites (RD4.2)"
    )
    assert "docs-check" in ci_steps_set, "CI_STEPS must still include docs-check"


def test_no_eval_scores_on_landing_readme() -> None:
    """Pin, expected GREEN: landing README must not publish eval benchmark scores."""
    text = _read(README)
    offenders: list[str] = []
    for index, line in enumerate(text.splitlines(), start=1):
        if not _EVAL_SCORE_TERMS.search(line):
            continue
        if _BENCHMARK_NUMBER.search(line):
            offenders.append(f"line {index}: {line.strip()}")
    assert not offenders, (
        "README must not publish precision/recall/F1 benchmark numbers on the landing page:\n"
        + "\n".join(offenders)
    )
