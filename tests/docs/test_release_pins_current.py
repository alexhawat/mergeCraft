"""The documents that quote a release name the current one (#1570).

``README.md`` installs a tagged release and links that tag's docs tree. Three
documents drifted behind it: ``docs/agents.md`` installed the previous alpha
and linked the previous tag's docs, ``SECURITY.md`` called the previous alpha
the latest pre-release, and ``evals/README.md`` restated a stale ref plus a
"same pin as README Example 1" claim nothing derived.

Nothing here hard-codes a release number. Every test reads the release from
``README.md``'s install line at run time, so the next release bump only has to
touch ``README.md`` -- and a document that lags it fails this module.
"""

from __future__ import annotations

import re

from mergecraft.pins import action_pin_minimal
from tests.ci.workflow_support import read_text

# ``uv tool install mergecraft-action==<release>`` -- the distribution name is
# the stable part; the version after ``==`` is what every document must repeat.
_INSTALL = re.compile(r"uv tool install mergecraft-action==(?P<version>\S+)")


def _readme_release() -> str:
    """Return the release ``README.md`` installs, e.g. ``0.1.0a6``."""
    match = _INSTALL.search(read_text("README.md"))
    assert match is not None, "README.md has no `uv tool install mergecraft-action==<release>` line"
    return match.group("version").strip()


def test_agents_page_installs_the_readme_release() -> None:
    """``docs/agents.md`` installs the release README installs, not an older one."""
    release = _readme_release()
    installed = re.findall(r"uv tool install mergecraft-action==(\S+)", read_text("docs/agents.md"))
    assert installed, "docs/agents.md no longer shows a `uv tool install mergecraft-action==` line"
    assert set(installed) == {release}, (
        f"docs/agents.md installs {sorted(set(installed))} but README.md installs {release}"
    )


def test_agents_page_links_the_current_docs_tree() -> None:
    """The docs-tree link in ``docs/agents.md`` names the release tag's tree."""
    release = _readme_release()
    text = read_text("docs/agents.md")
    trees = re.findall(r"https://github\.com/alexhawat/mergeCraft/tree/(v[^/\s)]+)/docs", text)
    assert trees, "docs/agents.md no longer links a tagged docs tree"
    assert set(trees) == {f"v{release}"}, (
        f"docs/agents.md links {sorted(set(trees))} but README.md's release is v{release}"
    )


def test_security_doc_names_the_current_pre_release() -> None:
    """``SECURITY.md`` Section Supported Versions names the release README installs."""
    release = _readme_release()
    text = read_text("SECURITY.md")
    match = re.search(r"^## Supported Versions\s*$(.*?)(?=^## )", text, re.MULTILINE | re.DOTALL)
    assert match is not None, "SECURITY.md has no `## Supported Versions` section"
    named = sorted(set(re.findall(r"\b\d+\.\d+\.\d+[A-Za-z0-9.\-]*\b", match.group(1))))
    assert named == [release], (
        f"SECURITY.md Supported Versions names {named}; only the current release "
        f"{release} that README.md installs may be the supported pre-release"
    )


def test_evals_readme_names_the_action_pin_minimal_value() -> None:
    """``evals/README.md`` quotes the ref the Harbor agent really defaults to."""
    pin = action_pin_minimal()
    text = read_text("evals/README.md")
    assert "action_pin_minimal" in text, (
        "evals/README.md must say the default install ref is whatever "
        "`action_pin_minimal()` returns"
    )
    assert pin in text, (
        f"evals/README.md never names the default install ref {pin!r} that "
        "`action_pin_minimal()` returns"
    )


def test_evals_readme_does_not_claim_the_readme_example_pins_the_same_ref() -> None:
    """The default-ref sentence must not restate an undrived same-pin claim."""
    offenders = [
        line.strip()
        for line in read_text("evals/README.md").splitlines()
        if "same pin" in line.lower()
    ]
    assert not offenders, (
        "evals/README.md still claims the default ref is the same pin as the README "
        f"example ({offenders}); name the value `action_pin_minimal()` returns instead"
    )
