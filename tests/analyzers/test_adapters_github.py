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

import httpx
import pytest

from tests.analyzers.support import (
    finding_path_matches,
    import_module,
    skip_if_github_release_outage,
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
    _fail_if_skipped(result, tool_id)
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


@pytest.mark.parametrize(
    ("detail", "expected", "transient_outage", "http_status", "download_url"),
    [
        (
            "",
            "502",
            True,
            502,
            "https://github.com/example/tool/releases/download/v1/tool",
        ),
        (
            "",
            "503",
            True,
            503,
            "https://github.com/example/tool/releases/download/v1/tool",
        ),
        (
            "",
            "504",
            True,
            504,
            "https://github.com/example/tool/releases/download/v1/tool",
        ),
        (
            "",
            "404",
            False,
            404,
            "https://github.com/example/tool/releases/download/v1/tool",
        ),
        (
            "",
            "503",
            False,
            503,
            "https://example.invalid/releases/download/v1/tool",
        ),
        (
            "sha256 checksum mismatch for downloaded artifact",
            "checksum mismatch",
            False,
            None,
            None,
        ),
        (
            "refusing redirect from pinned download url to an unsafe host",
            "refusing redirect",
            False,
            None,
            None,
        ),
        ("unexpected provisioning failure", "unexpected provisioning failure", False, None, None),
        ("", "unspecified error", False, None, None),
    ],
)
def test_managed_provisioning_preserves_final_redacted_failure_cause(
    detail: str,
    expected: str,
    transient_outage: bool,
    http_status: int | None,
    download_url: str | None,
    adapter_fixture_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mergecraft.analyzers import adapters as adapters_mod
    from mergecraft.analyzers import execution
    from mergecraft.analyzers.provision import ProvisionError
    from mergecraft.analyzers.resolve import AnalyzerPlan

    plan = AnalyzerPlan(manifest_id="hadolint", mode="managed", argv=("hadolint",))
    attempts = 0

    def fail_provision(**_kwargs: object) -> None:
        nonlocal attempts
        attempts += 1
        if http_status is not None and download_url is not None:
            request = httpx.Request("GET", download_url)
            response = httpx.Response(http_status, request=request)
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise ProvisionError(f"download failed for {download_url!r}: {exc}") from exc
            pytest.fail("test HTTP status did not raise")
        raise ProvisionError(detail)

    monkeypatch.setattr(adapters_mod, "resolve_analyzer", lambda **_kwargs: plan)
    monkeypatch.setattr(execution, "resolve_baked_binary", lambda _manifest: None)
    monkeypatch.setattr(execution, "resolve_with_lock", fail_provision)
    monkeypatch.setattr(execution.time, "sleep", lambda _seconds: None)

    result = adapters_mod.run_adapter(
        tool_id="hadolint",
        repo_root=adapter_fixture_repo,
        changed_files=["Dockerfile"],
        tier="trusted",
    )

    assert attempts == 3
    assert result.skipped is True
    reason = result.skip_reason or ""
    assert expected in reason
    assert "https://" not in reason
    if transient_outage:
        with pytest.raises(pytest.skip.Exception):
            skip_if_github_release_outage(reason)
    else:
        assert skip_if_github_release_outage(reason) is None


def test_managed_provisioning_redacts_and_bounds_failure_cause(
    adapter_fixture_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mergecraft.analyzers import adapters as adapters_mod
    from mergecraft.analyzers import execution
    from mergecraft.analyzers.provision import ProvisionError
    from mergecraft.analyzers.resolve import AnalyzerPlan

    canary = "ghp_1234567890abcdefghijklmnop"
    detail = f"download failed for https://example.invalid/tool?token={canary}: {canary}" + (
        "x" * 2_000
    )
    plan = AnalyzerPlan(manifest_id="hadolint", mode="managed", argv=("hadolint",))
    monkeypatch.setattr(adapters_mod, "resolve_analyzer", lambda **_kwargs: plan)
    monkeypatch.setattr(execution, "resolve_baked_binary", lambda _manifest: None)
    monkeypatch.setattr(
        execution,
        "resolve_with_lock",
        lambda **_kwargs: (_ for _ in ()).throw(ProvisionError(detail)),
    )
    monkeypatch.setattr(execution.time, "sleep", lambda _seconds: None)

    result = adapters_mod.run_adapter(
        tool_id="hadolint",
        repo_root=adapter_fixture_repo,
        changed_files=["Dockerfile"],
        tier="trusted",
    )

    reason = result.skip_reason or ""
    assert canary not in reason
    assert "https://" not in reason
    assert "<redacted>" in reason
    assert len(reason) <= 512


def test_provisioning_failure_formatter_handles_malformed_url_and_long_tool_id() -> None:
    from mergecraft.analyzers.execution import provisioning_failure_reason
    from mergecraft.analyzers.provision import ProvisionError

    malformed_reason = provisioning_failure_reason("tool", ProvisionError("https://["))
    long_id_reason = provisioning_failure_reason(
        "tool-" + ("x" * 1_000), ProvisionError("download failed")
    )

    assert "<redacted-url>" in malformed_reason
    assert "https://" not in malformed_reason
    assert len(long_id_reason) == 512


def test_semgrep_provisioning_error_uses_the_same_visible_contract(
    adapter_fixture_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mergecraft.analyzers import adapters as adapters_mod
    from mergecraft.analyzers import pattern
    from mergecraft.analyzers.resolve import AnalyzerPlan

    plan = AnalyzerPlan(manifest_id="semgrep", mode="managed", argv=("semgrep",))
    monkeypatch.setattr(adapters_mod, "resolve_analyzer", lambda **_kwargs: plan)
    monkeypatch.setattr(
        pattern,
        "provision_pip_script",
        lambda **_kwargs: (_ for _ in ()).throw(OSError("pip cache is read-only")),
    )

    result = adapters_mod.run_adapter(
        tool_id="semgrep",
        repo_root=adapter_fixture_repo,
        changed_files=["action.yml"],
        tier="trusted",
    )

    assert result.skipped is True
    assert "managed binary provisioning failed" in (result.skip_reason or "")
    assert "pip cache is read-only" in (result.skip_reason or "")
