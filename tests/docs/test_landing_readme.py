"""RD2 — outline-B landing README contracts.

Pins the REACH-style landing page: outline-B headings, problem/solution cards,
D2 architecture ``<picture>``, numbered install, Example 1 workflow pin, satellite
page moves, and the G1 docs-site badge regression guard.
"""

from __future__ import annotations

import re

from tests.ci.workflow_support import REPO_ROOT, read_text
from tests.docs.support import action_uses_pattern, git_ref_exists

README = REPO_ROOT / "README.md"
_D2_SOURCE = REPO_ROOT / "docs" / "diagrams" / "pipeline.d2"
_PIPELINE_LIGHT = REPO_ROOT / "assets" / "diagrams" / "pipeline-light.svg"
_PIPELINE_DARK = REPO_ROOT / "assets" / "diagrams" / "pipeline-dark.svg"
_PAGES = "https://alexhawat.github.io/mergeCraft/"

_DEMO_PATHS = (
    "docs/assets/demo.gif",
    "assets/demo.gif",
    "assets/demo.mp4",
)


def _readme_text() -> str:
    return read_text("README.md")


def _section_body(text: str, heading_pattern: str) -> str | None:
    match = re.search(
        rf"^##\s+{heading_pattern}[^\n]*\n(.*?)(?=^## |\Z)",
        text,
        re.MULTILINE | re.DOTALL,
    )
    return match.group(1) if match else None


def _jump_nav_targets(text: str) -> set[str]:
    nav_match = re.search(r"^\[(?:[^\]]+\]\([^)]+\)\s*·\s*)+[^\]]+\]\([^)]+\)", text, re.MULTILINE)
    if not nav_match:
        return set()
    return {
        target.split("#", 1)[-1].lower()
        for target in re.findall(r"\]\(#([^)]+)\)", nav_match.group(0))
    }


def _heading_slugs(text: str) -> set[str]:
    slugs: set[str] = set()
    for line in text.splitlines():
        if not line.startswith("## "):
            continue
        slug = re.sub(r"[^\w\s-]", "", line[3:].strip()).lower()
        slug = re.sub(r"\s+", "-", slug).strip("-")
        if slug:
            slugs.add(slug)
    return slugs


def _anchor_present(text: str, *needles: str) -> bool:
    slugs = _heading_slugs(text)
    nav = _jump_nav_targets(text)
    haystack = slugs | nav | {text.lower()}
    return any(needle.lower() in haystack for needle in needles)


def _example_one_section(text: str) -> str:
    match = re.search(
        r"### Example 1[^\n]*\n(.*?)(?=\n### Example 2|\n## [^\#]|\Z)",
        text,
        re.DOTALL,
    )
    assert match, "README must keep Example 1 / auto-review workflow under RD2 outline B"
    return match.group(1)


def test_landing_has_outline_b_headings() -> None:
    text = _readme_text()
    missing: list[str] = []
    if not _anchor_present(text, "problem", "why"):
        missing.append("Problem or Why")
    if not _anchor_present(text, "how-it-works", "how it works"):
        missing.append("How it works")
    if not _anchor_present(text, "install"):
        missing.append("Install")
    if not _anchor_present(text, "features"):
        missing.append("Features")
    if not _anchor_present(text, "documentation", "docs"):
        missing.append("Documentation")
    assert not missing, f"README missing outline-B headings or jump-nav anchors: {missing}"


def test_landing_has_problem_solution_cards() -> None:
    text = _readme_text()
    region = _section_body(text, r".*(?:Problem|Why)")
    assert region is not None, "README needs a Problem/Why section for outline-B cards"
    has_table = bool(re.search(r"^\|.*\|\s*\n\|[-:\s|]+\|", region, re.MULTILINE))
    card_headings = re.findall(r"^###\s+", region, re.MULTILINE)
    assert has_table or len(card_headings) >= 3, (
        "Problem/solution region needs a markdown table or three ### cards (RD2.2)"
    )


def test_landing_has_picture_architecture_diagram() -> None:
    text = _readme_text()
    assert "assets/diagrams/pipeline-dark.svg" in text, (
        "README architecture hero must reference assets/diagrams/pipeline-dark.svg"
    )
    assert "assets/diagrams/pipeline-light.svg" in text, (
        "README architecture hero must reference assets/diagrams/pipeline-light.svg"
    )
    assert "<picture>" in text, "README must wrap the architecture hero in a <picture> element"


def test_diagram_svgs_exist_and_are_nonempty() -> None:
    for path in (_PIPELINE_LIGHT, _PIPELINE_DARK):
        assert path.is_file(), f"missing committed diagram {path.relative_to(REPO_ROOT)} (RD2.2)"
        assert path.stat().st_size > 0, f"{path.name} must be non-empty"


def test_d2_source_exists() -> None:
    assert _D2_SOURCE.is_file(), f"missing {_D2_SOURCE.relative_to(REPO_ROOT)} (RD2.2)"
    text = _D2_SOURCE.read_text(encoding="utf-8").lower()
    assert any(token in text for token in ("trust", "verifier", "findings")), (
        "docs/diagrams/pipeline.d2 must mention trust, verifier, or findings"
    )


def test_landing_omits_broken_demo_image() -> None:
    """Pin, expected GREEN: landing omits demo paths until a real capture exists."""
    text = _readme_text()
    broken: list[str] = []
    for rel in _DEMO_PATHS:
        if rel in text and not (REPO_ROOT / rel).is_file():
            broken.append(rel)
    assert not broken, f"README references demo assets that are not tracked: {broken}"


def test_landing_has_numbered_install() -> None:
    text = _readme_text()
    region = _section_body(text, r"Install\b")
    assert region is not None, "README needs an Install section with numbered steps (RD2.2)"
    numbered = re.search(r"(?:^|\n)\s*1\.\s+", region)
    assert numbered, "Install section must use ordered steps"
    lowered = region.lower()
    assert "uses:" in lowered or "alexhawat/mergecraft@" in lowered, (
        "Install steps must document the GitHub Action path"
    )
    assert "mergecraft auth" in lowered, "Install steps must document provider auth"
    assert any(
        token in lowered for token in ("pull request", "@mergecraft review", "workflow_dispatch")
    ), "Install steps must document how to trigger a review"


def test_landing_keeps_example_one_workflow() -> None:
    text = _readme_text()
    section = _example_one_section(text)
    uses_match = action_uses_pattern.search(section)
    assert uses_match, "Example 1 must include uses: alexhawat/mergeCraft@…"
    ref = uses_match.group(1).rstrip("#").strip()
    assert git_ref_exists(ref), (
        f"Example 1 Action ref {ref!r} must resolve to an existing tag, branch, or commit (D25)"
    )


def test_landing_action_section_is_named_for_github_action() -> None:
    text = _readme_text()
    assert re.search(
        r"^##\s+How it works in GitHub Action\s*$",
        text,
        re.MULTILINE | re.IGNORECASE,
    ), "README must rename How it works → How it works in GitHub Action (A4)"


def test_landing_pins_a_release_tag() -> None:
    text = _readme_text()
    section = _example_one_section(text)
    uses_match = action_uses_pattern.search(section)
    assert uses_match, "Example 1 must include uses: alexhawat/mergeCraft@…"
    ref = uses_match.group(1).rstrip("#").strip()
    assert re.fullmatch(r"v\d+\.\d+\.\d+(?:a\d+|b\d+|rc\d+)?", ref, re.IGNORECASE), (
        f"Example 1 must pin a release tag (vX.Y.Z), not {ref!r} (A6/D7)"
    )


def test_landing_has_no_sha_pin_caveat() -> None:
    text = _readme_text()
    assert "Pin to a full commit SHA" not in text, (
        "README must drop the Pin to a full commit SHA caveat once tags ship (A6)"
    )


def test_landing_does_not_contain_full_cli_table() -> None:
    """Pin, expected GREEN after RD1: full CLI table lives in docs/cli.md."""
    text = _readme_text()
    assert not re.search(r"\|\s*Command\s*\|\s*Description\s*\|", text), (
        "README must not host the full generated CLI table (docs/cli.md owns it)"
    )
    assert "mergecraft agents list" not in text, (
        "README must not embed mergecraft agents list from the full CLI table"
    )


def test_satellite_pages_received_moved_essays() -> None:
    workflows = REPO_ROOT / "docs" / "workflows.md"
    authentication = REPO_ROOT / "docs" / "authentication.md"
    install = REPO_ROOT / "docs" / "install.md"
    assert workflows.is_file(), "docs/workflows.md must exist (RD2.2 satellite move)"
    assert authentication.is_file(), "docs/authentication.md must exist (RD2.2 satellite move)"
    assert install.is_file(), "docs/install.md must exist (RD2.2 satellite move)"

    workflows_text = workflows.read_text(encoding="utf-8")
    auth_text = authentication.read_text(encoding="utf-8")
    install_text = install.read_text(encoding="utf-8")

    assert "pull_request_target" in workflows_text, (
        "docs/workflows.md must carry the pull_request_target gotchas moved off the landing page"
    )
    assert "MERGECRAFT_CUSTOM_PROVIDER" in auth_text or "openai-compatible" in auth_text.lower(), (
        "docs/authentication.md must document custom OpenAI-compatible providers"
    )
    assert "3.11" in install_text, "docs/install.md must document the Python 3.11+ floor (#343)"


def test_no_docs_site_badge() -> None:
    """Pin, expected GREEN: G1 removed the unpublished docs-site badge and links."""
    text = _readme_text()
    assert _PAGES not in text
    assert "docs-mergecraft.dev" not in text
