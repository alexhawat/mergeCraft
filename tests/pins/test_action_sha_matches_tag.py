"""The `action_sha_minimal` key must name the commit its release tag points to.

Harbor installs mergeCraft by the release tag (`action_pin_minimal`), while
workflows `uses:` the immutable commit (`action_sha_minimal`). The two are
updated by hand, so they rot independently; `make pins-check` runs the live
`git ls-remote` comparison. This test replays the same comparison against a
recorded `git ls-remote --tags` capture so the drift gate is exercised offline.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mergecraft.pins import action_pin_minimal, load_example_defaults

_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "git_ls_remote_tags.txt"


def _recorded_tag_commits() -> dict[str, str]:
    """Parse recorded ``git ls-remote --tags`` rows into ``tag -> commit``."""
    commits: dict[str, str] = {}
    for raw_line in _FIXTURE.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        fields = line.split()
        assert len(fields) >= 2, f"unexpected ls-remote fixture row: {raw_line!r}"
        sha, ref = fields[0], fields[1]
        tag = ref.removeprefix("refs/tags/").removesuffix("^{}")
        commits[tag] = sha
    return commits


@pytest.mark.xfail(reason="green after SW3.1: action_sha_minimal key added", strict=False)
def test_action_sha_matches_the_tag_it_ships_with() -> None:
    commits = _recorded_tag_commits()
    tag = action_pin_minimal()
    assert tag in commits, f"fixture has no recorded commit for {tag!r}"
    assert load_example_defaults().get("action_sha_minimal") == commits[tag], (
        f"action_sha_minimal must equal the commit {tag} resolves to; "
        "otherwise the workflow runs different code than Harbor installs"
    )
