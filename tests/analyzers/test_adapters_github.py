"""W6 GitHub-native adapters against the W0.8 fixture repo.

Every assertion here reads the *whole* :class:`AdapterRunResult`, never just
``.findings``. ``run_adapter`` distinguishes "the tool did not run" from "the
tool ran and found nothing", and a test that discards ``.skipped`` /
``.skip_reason`` cannot tell them apart — an unprovisioned ``hadolint`` then
reads as a detection miss in one test and as a clean pass in its sibling, in
the same run (#805). The sibling suites in this directory
(``test_adapters_parse.py``, ``test_adapters_supply_chain.py``,
``test_adapters_contract.py``, ``test_adapters_language.py``) already assert on
those fields; this file is the one that did not.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from tests.analyzers.support import (
    finding_path_matches,
    import_module,
    skip_if_managed_binary_provision_failed,
)

if TYPE_CHECKING:
    from pathlib import Path

    from mergecraft.analyzers.adapters import AdapterRunResult

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


def _fail_if_skipped(result: AdapterRunResult, tool_id: str) -> None:
    """Fail distinctly when the tool never ran — never as a detection miss.

    An unprovisioned tool produces no findings, which is *not* the same result
    as a tool that ran and missed the planted defect. Saying "must catch
    planted finding" here sends the reader after a regression that does not
    exist; quoting ``skip_reason`` names provisioning instead (#805).
    """
    if result.skipped:
        pytest.fail(f"{tool_id} did not run: {result.skip_reason}")


@pytest.mark.parametrize("tool_id", list(PLANTED))
def test_adapter_catches_planted_finding(tool_id: str, adapter_fixture_repo: Path) -> None:
    adapters = import_module("mergecraft.analyzers.adapters")
    path, line = PLANTED[tool_id]
    result = adapters.run_adapter(
        tool_id=tool_id,
        repo_root=adapter_fixture_repo,
        changed_files=[path],
        tier="trusted",
    )
    skip_if_managed_binary_provision_failed(result)
    matches = [
        f for f in result.findings if finding_path_matches(path, f.path) and f.start_line == line
    ]
    assert matches, f"{tool_id} must catch planted finding at {path}:{line}"


@pytest.mark.parametrize("tool_id", list(PLANTED))
def test_adapter_invents_no_unplanted_findings_on_untouched_files(
    tool_id: str, adapter_fixture_repo: Path
) -> None:
    adapters = import_module("mergecraft.analyzers.adapters")
    result = adapters.run_adapter(
        tool_id=tool_id,
        repo_root=adapter_fixture_repo,
        changed_files=[PLANTED[tool_id][0]],
        tier="trusted",
    )
    # An unprovisioned tool returns no findings, so an absence assertion would
    # pass green for the wrong reason. Surface the skip first, then assert the
    # absence only over a run that actually happened (#805).
    _fail_if_skipped(result, tool_id)
    reported_paths = {f.path for f in result.findings}
    for untouched in UNTOUCHED_PATHS:
        assert untouched not in reported_paths


def test_unprovisioned_managed_tool_skips_with_a_provisioning_reason(
    adapter_fixture_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unprovisioned tool yields ``skipped`` with a provisioning reason.

    Direct proof of the distinction both tests above depend on: simulate the
    managed-binary provisioning seam exactly as ``no provenance for platform
    …`` does in production (``resolve_analyzer`` resolves a managed plan,
    ``provision_managed_argv`` fails to provision it), and assert the result
    carries ``skipped is True`` with a non-empty reason naming provisioning —
    not an empty finding list that reads as a clean detection.
    """
    from mergecraft.analyzers import adapters as adapters_mod
    from mergecraft.analyzers.resolve import AnalyzerPlan

    plan = AnalyzerPlan(manifest_id="hadolint", mode="managed", argv=("hadolint",))

    monkeypatch.setattr(adapters_mod, "resolve_analyzer", lambda **_kwargs: plan)
    monkeypatch.setattr(adapters_mod, "provision_managed_argv", lambda *_args, **_kwargs: None)

    result = adapters_mod.run_adapter(
        tool_id="hadolint",
        repo_root=adapter_fixture_repo,
        changed_files=["Dockerfile"],
        tier="trusted",
    )

    assert result.findings == []
    assert result.skipped is True
    reason = result.skip_reason or ""
    assert "provisioning" in reason, reason
