"""``integrations/`` has one self-describing directory per host (#845).

The rule for where a new integration goes is written down (CONTRIBUTING and the
index at ``integrations/README.md``); each host directory carries a README; and the
files a host dictates the location of stay where the host reads them, with the
README pointing at them rather than moving them.
"""

from __future__ import annotations

import re
from pathlib import Path

from tests.ci.workflow_support import REPO_ROOT, read_text

_INTEGRATIONS = REPO_ROOT / "integrations"
_LINK = re.compile(r"\]\(([^)#]+?)(?:#[^)]*)?\)")


def _host_dirs() -> list[Path]:
    return sorted(path for path in _INTEGRATIONS.iterdir() if path.is_dir())


def test_every_host_directory_has_a_readme() -> None:
    hosts = _host_dirs()
    assert {path.name for path in hosts} >= {"opencode", "claude", "copilot"}
    for host in hosts:
        assert (host / "README.md").is_file(), f"integrations/{host.name} has no README.md"


def test_the_pointer_readmes_link_to_files_that_exist() -> None:
    for host in ("claude", "copilot"):
        readme = _INTEGRATIONS / host / "README.md"
        targets = _LINK.findall(readme.read_text(encoding="utf-8"))
        assert targets, f"{readme} links to nothing"
        for target in targets:
            if target.startswith(("http://", "https://")):
                continue
            assert (readme.parent / target).resolve().exists(), f"{readme}: dead link {target}"


def test_host_dictated_locations_did_not_move() -> None:
    for relative in (
        ".claude-plugin/plugin.json",
        "commands/mergecraft-review.md",
        ".github/skills/code-review/SKILL.md",
    ):
        assert (REPO_ROOT / relative).is_file(), f"{relative} must stay where the host reads it"


def test_contributing_states_the_rule_and_the_python_split() -> None:
    text = read_text("CONTRIBUTING.md")
    assert "`integrations/`" in text
    assert "one directory per host" in text
    assert "src/mergecraft/integrations/" in text
    assert "integrations/README.md" in text


def test_the_index_names_every_host_directory() -> None:
    index = (_INTEGRATIONS / "README.md").read_text(encoding="utf-8")
    for host in _host_dirs():
        assert f"integrations/{host.name}/" in index, f"index omits {host.name}"
