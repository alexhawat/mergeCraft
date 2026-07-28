"""W6 GitHub-native adapters against the W0.8 fixture repo."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.analyzers.support import import_module

PLANTED: dict[str, tuple[str, int]] = {
    "actionlint": (".github/workflows/broken.yml", 2),
    "zizmor": (".github/workflows/unpinned-action.yml", 11),
    "shellcheck": ("scripts/deploy.sh", 5),
    "hadolint": ("Dockerfile", 2),
}

UNTOUCHED_PATHS = (
    "db/migrations/001_add_users.sql",
    "openapi/v1.yaml",
    "requirements.txt",
)


@pytest.mark.parametrize("tool_id", list(PLANTED))
def test_adapter_catches_planted_finding(tool_id: str, fixture_repo: Path) -> None:
    adapters = import_module("mergecraft.analyzers.adapters")
    path, line = PLANTED[tool_id]
    findings = adapters.run_adapter(
        tool_id=tool_id,
        repo_root=fixture_repo,
        changed_files=[path],
        tier="trusted",
    )
    matches = [f for f in findings if f.path == path and f.start_line == line]
    assert matches, f"{tool_id} must catch planted finding at {path}:{line}"


@pytest.mark.parametrize("tool_id", list(PLANTED))
def test_adapter_invents_no_unplanted_findings_on_untouched_files(
    tool_id: str, fixture_repo: Path
) -> None:
    adapters = import_module("mergecraft.analyzers.adapters")
    findings = adapters.run_adapter(
        tool_id=tool_id,
        repo_root=fixture_repo,
        changed_files=[PLANTED[tool_id][0]],
        tier="trusted",
    )
    reported_paths = {f.path for f in findings}
    for untouched in UNTOUCHED_PATHS:
        assert untouched not in reported_paths
