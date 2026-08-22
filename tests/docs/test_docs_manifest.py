"""RD1.1 — docs manifest, templates, and generated index (RED until RD1.2).

Pins ``docs/manifest.yaml``, the four ``docs/_templates/*.md.tpl`` files,
``docs/README.md`` as a manifest-driven index, and ``make docs-check`` in
``CI_STEPS``. Implementation lands in RD1.2.
"""

from __future__ import annotations

import re
from typing import Any

import yaml

from tests.ci.workflow_support import REPO_ROOT, read_text
from tests.docs.support import ci_steps

_MANIFEST = REPO_ROOT / "docs" / "manifest.yaml"
_DOCS_INDEX = REPO_ROOT / "docs" / "README.md"
_TEMPLATES_DIR = REPO_ROOT / "docs" / "_templates"

_REQUIRED_MANIFEST_PATHS = (
    "README.md",
    "docs/cli.md",
    "docs/action-reference.md",
    "docs/ANALYZERS.md",
    "CONTRIBUTING.md",
    "REVIEW-CHECKS.md",
    "evals/README.md",
)

_TEMPLATE_NAMES = ("consumer", "generated-ref", "contributor", "satellite")

_EXCLUDED_MANIFEST_PREFIXES = ("docs/test-plans/", "docs/artifacts/")


def _load_manifest() -> dict[str, Any]:
    assert _MANIFEST.is_file(), f"missing {_MANIFEST.relative_to(REPO_ROOT)} (RD1.2)"
    data = yaml.safe_load(_MANIFEST.read_text(encoding="utf-8"))
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
        assert path.strip(), "each manifest row needs a non-empty path:"
        paths.append(path)
    return paths


def _markdown_links(text: str) -> set[str]:
    """Return repo-relative targets from markdown ``[label](target)`` links."""
    links: set[str] = set()
    for match in re.finditer(r"\]\(([^)]+)\)", text):
        target = match.group(1).strip()
        if not target or target.startswith(("http://", "https://", "#", "mailto:")):
            continue
        links.add(target.split("#", 1)[0])
    return links


def test_manifest_lists_required_pages() -> None:
    manifest = _load_manifest()
    paths = set(_manifest_paths(manifest))
    missing = sorted(set(_REQUIRED_MANIFEST_PATHS) - paths)
    assert not missing, f"docs/manifest.yaml missing required pages: {missing}"
    excluded = sorted(
        path
        for path in paths
        if any(path == prefix or path.startswith(prefix) for prefix in _EXCLUDED_MANIFEST_PREFIXES)
    )
    assert not excluded, (
        "docs/manifest.yaml must not list per-wave working trees: "
        f"{excluded} (exclude {_EXCLUDED_MANIFEST_PREFIXES})"
    )


def _index_href_to_manifest_path(href: str) -> str | None:
    """Map a ``docs/README.md`` link target back to a manifest ``path`` value."""
    if href == "manifest.yaml":
        return None
    if href.startswith("../"):
        return href.removeprefix("../")
    return f"docs/{href}"


def _manifest_paths_linked_from_index(index_text: str) -> set[str]:
    linked = _markdown_links(index_text)
    resolved = {_index_href_to_manifest_path(href) for href in linked}
    return {path for path in resolved if path is not None}


def test_generated_docs_index_lists_every_manifest_row() -> None:
    manifest = _load_manifest()
    paths = _manifest_paths(manifest)
    assert _DOCS_INDEX.is_file(), f"missing {_DOCS_INDEX.relative_to(REPO_ROOT)} (RD1.2)"
    index_text = _DOCS_INDEX.read_text(encoding="utf-8")
    linked_paths = _manifest_paths_linked_from_index(index_text)
    missing_links = sorted(path for path in paths if path not in linked_paths)
    assert not missing_links, (
        f"docs/README.md must link every manifest row; missing links for: {missing_links}"
    )


def test_templates_exist() -> None:
    missing_files: list[str] = []
    bad_templates: list[str] = []
    for name in _TEMPLATE_NAMES:
        path = _TEMPLATES_DIR / f"{name}.md.tpl"
        if not path.is_file():
            missing_files.append(str(path.relative_to(REPO_ROOT)))
            continue
        text = path.read_text(encoding="utf-8")
        if "{{PURPOSE}}" not in text:
            bad_templates.append(f"{path.name}: missing {{{{PURPOSE}}}} slot")
        if "{{SEE_ALSO}}" not in text and "See also" not in text:
            bad_templates.append(f"{path.name}: missing See also / {{{{SEE_ALSO}}}} slot")
    assert not missing_files, f"missing template files: {missing_files}"
    assert not bad_templates, "\n".join(bad_templates)


def _makefile_prerequisite_tokens(makefile: str, target: str) -> set[str]:
    match = re.search(rf"^{re.escape(target)}:(.*)$", makefile, re.MULTILINE)
    assert match, f"Makefile missing {target}: recipe"
    return set(match.group(1).split())


def test_make_docs_check_is_in_ci_steps() -> None:
    """D3: ``docs-check`` supersedes ``reference-docs-check`` in ``CI_STEPS`` (RD1.2)."""
    makefile = read_text("Makefile")
    ci_steps_set = set(ci_steps())
    ci_static = _makefile_prerequisite_tokens(makefile, "ci-static")
    assert "docs-check" in ci_steps_set, (
        "Makefile CI_STEPS must include docs-check (not reference-docs-check substring)"
    )
    assert "docs-check" in ci_static, (
        "Makefile ci-static must include docs-check (RD1.2 replaces reference-docs-check)"
    )
