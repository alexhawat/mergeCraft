"""#35 — split the `shell: disabled` withhold (Batch A, W1).

Today `analyzers_enabled()` collapses two unrelated questions into one boolean:

* may the reviewer run **repo-declared `staticChecks`** — PR-authored command
  strings, which `shell: disabled` exists to forbid; and
* may the reviewer run **mergeCraft's own pinned catalog analyzers** — argv
  that comes verbatim from a manifest mergeCraft ships.

Answering "no" to both means a repo that hardens correctly (`pull_request_target`
plus `shell: disabled`) gets *zero* mechanical coverage on its only real PR path.

These cases pin the split:

* the analyzer surface registers on a real PR event under `shell: disabled`;
* `run_static_checks` stays withheld unconditionally (D7);
* only `runtime: managed` / `runtime: container` manifests are eligible, and
  every ineligible one is skipped with a named reason (D5, D9);
* a repo-provided binary can never stand in for the pinned managed one on that
  path — the steerability vector W0.4 found in ``resolve_analyzer()``;
* the fork/untrusted and offline paths behave exactly as they did before.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from mergecraft.analyzers.registry import get_manifest, load_catalog
from mergecraft.analyzers.resolve import resolve_analyzer
from mergecraft.analyzers.trust import (
    analyzers_enabled,
    build_analyzer_env,
    evaluate_manifest_for_tier,
)
from mergecraft.mcp.context import (
    PayloadEvent,
    RepoIdentity,
    ResolvedPayload,
    ToolContext,
)
from mergecraft.mcp.server import build_common_tools
from mergecraft.mcp.tool_state import init_tool_state
from mergecraft.modes import compute_modes
from mergecraft.utils.github import GitHubClient
from tests.analyzers.support import import_module

if TYPE_CHECKING:
    from mergecraft.analyzers.manifest import AnalyzerManifest


def _evaluate_manifest_for_shell(*, manifest: AnalyzerManifest, shell: str) -> Any:
    """Lazy so the module still collects before W2 adds the predicate (W1.8)."""
    trust = import_module("mergecraft.analyzers.trust")
    return trust.evaluate_manifest_for_shell(manifest=manifest, shell=shell)


def _allow_repo_provided_binaries(*, shell: str) -> Any:
    trust = import_module("mergecraft.analyzers.trust")
    return trust.allow_repo_provided_binaries(shell=shell)


# Real PR triggers — everything that is not the operator-owned offline path.
PR_TRIGGERS: tuple[str, ...] = ("pull_request", "pull_request_target", "issue_comment")

# One representative per eligible runtime, plus the ineligible ones W1.3 sweeps.
MANAGED_ANALYZER_ID = "shellcheck"
CONTAINER_ANALYZER_ID = "presidio"


def _manifest(analyzer_id: str) -> AnalyzerManifest:
    return get_manifest(analyzer_id)


def _catalog_manifests() -> list[AnalyzerManifest]:
    return sorted(load_catalog(), key=lambda m: m.id)


def _ids_by_runtime(runtime: str) -> list[str]:
    return sorted(m.id for m in _catalog_manifests() if m.runtime == runtime)


# `agentsec` and `antislop` declare `repo-native` but run in-process with no subprocess
# and no repo-provided binary, so the "needs repo tooling" premise this axis rests on is
# false for them. Batch A withheld `agentsec` anyway and flagged it; #38 admits it
# deliberately — see `IN_PROCESS_ANALYZER_IDS` in `analyzers/trust.py`.
IN_PROCESS_IDS: frozenset[str] = frozenset({"agentsec", "antislop"})

REPO_NATIVE_IDS: list[str] = [
    analyzer_id
    for analyzer_id in _ids_by_runtime("repo-native")
    if analyzer_id not in IN_PROCESS_IDS
]
ELIGIBLE_IDS: list[str] = sorted(
    _ids_by_runtime("managed") + _ids_by_runtime("container") + sorted(IN_PROCESS_IDS)
)


def _ctx(
    tmp_path: Path,
    *,
    shell: str = "disabled",
    trigger: str = "pull_request",
    static_checks_enabled: bool = False,
    analyzers_mode: str = "auto",
    analyzers_settings_enabled: bool = True,
    tier: str = "untrusted",
) -> ToolContext:
    return ToolContext(
        agent_id="claude",
        repo=RepoIdentity(owner="acme", name="demo"),
        payload=ResolvedPayload(
            event=PayloadEvent(trigger=trigger),
            shell=shell,  # type: ignore[arg-type]
        ),
        github=GitHubClient(token=""),
        github_installation_token="",
        git_token="",
        api_token="",
        modes=compute_modes("claude"),
        tool_state=init_tool_state(owner="acme", name="demo", dir=str(tmp_path)),
        mcp_server_url="",
        tmpdir=str(tmp_path),
        static_checks_enabled=static_checks_enabled,
        analyzers_mode=analyzers_mode,  # type: ignore[arg-type]
        analyzers_settings_enabled=analyzers_settings_enabled,
        trust_tier=tier,  # type: ignore[arg-type]
    )


def _tool_names(ctx: ToolContext) -> set[str]:
    return {spec.name for spec in build_common_tools(ctx)}


# --------------------------------------------------------------------------- #
# W1.1 — the analyzer surface registers under `shell: disabled` on a PR event
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("trigger", PR_TRIGGERS)
def test_managed_analyzers_register_when_shell_disabled_on_pr_event(
    tmp_path: Path, trigger: str
) -> None:
    """#35's headline: a hardened repo's real PR path gets the analyzer tools."""
    ctx = _ctx(tmp_path, shell="disabled", trigger=trigger)
    assert analyzers_enabled(ctx) is True
    assert {"run_analyzers", "analyzer_findings"} <= _tool_names(ctx)


def test_shell_disabled_surface_still_respects_the_off_switches(tmp_path: Path) -> None:
    """The split must not swallow the two pre-existing short-circuits."""
    off = _ctx(tmp_path, shell="disabled", analyzers_mode="off")
    assert analyzers_enabled(off) is False
    assert "run_analyzers" not in _tool_names(off)

    disabled_in_config = _ctx(tmp_path, shell="disabled", analyzers_settings_enabled=False)
    assert analyzers_enabled(disabled_in_config) is False
    assert "run_analyzers" not in _tool_names(disabled_in_config)


# --------------------------------------------------------------------------- #
# W1.2 — `run_static_checks` stays withheld unconditionally (D7)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("trigger", PR_TRIGGERS)
def test_static_checks_still_withheld_when_shell_disabled(tmp_path: Path, trigger: str) -> None:
    """D7: PR-authored command construction is exactly what `disabled` forbids."""
    ctx = _ctx(tmp_path, shell="disabled", trigger=trigger, static_checks_enabled=False)
    names = _tool_names(ctx)
    assert "run_static_checks" not in names
    # ...while the analyzer surface, which runs no PR-authored command, is present.
    assert "run_analyzers" in names


def test_declared_static_checks_still_report_declared_but_cannot_run() -> None:
    """The PR-#17 outcome vocabulary is reused, not replaced (D9)."""
    from mergecraft.review_checks import StaticCheck, declared_cannot_run_outcomes

    checks = [StaticCheck(name="lint", argv=("make", "lint"))]
    outcomes = declared_cannot_run_outcomes(checks, reason="shell: disabled")
    assert [row.status for row in outcomes] == ["declared-but-cannot-run"]
    assert outcomes[0].output == "shell: disabled"
    assert outcomes[0].ran is False


# --------------------------------------------------------------------------- #
# W1.3 / W1.7 — eligibility is keyed on the declared runtime, skips are named
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("analyzer_id", REPO_NATIVE_IDS)
def test_repo_native_analyzers_skipped_when_shell_disabled(analyzer_id: str) -> None:
    """D5: `repo-native` resolves against repo-provided tooling, so it stays withheld."""
    decision = _evaluate_manifest_for_shell(manifest=_manifest(analyzer_id), shell="disabled")
    assert decision.skipped is True
    assert decision.reason
    assert analyzer_id in decision.reason


@pytest.mark.parametrize("analyzer_id", ELIGIBLE_IDS)
def test_managed_and_container_analyzers_pass_the_shell_gate(analyzer_id: str) -> None:
    """D5: pinned mergeCraft argv is eligible; 33 of the 57 shipped manifests."""
    decision = _evaluate_manifest_for_shell(manifest=_manifest(analyzer_id), shell="disabled")
    assert decision.skipped is False
    assert decision.reason is None


@pytest.mark.parametrize("shell", ["restricted", "enabled"])
def test_shell_gate_is_inert_when_shell_is_not_disabled(shell: str) -> None:
    """A regression guard: the new predicate must change nothing off its own path."""
    for analyzer_id in (MANAGED_ANALYZER_ID, "ruff"):
        decision = _evaluate_manifest_for_shell(manifest=_manifest(analyzer_id), shell=shell)
        assert decision.skipped is False


def test_skip_reasons_are_named_not_silent() -> None:
    """D9: every skip is an outcome with a human-readable reason, never a silent drop."""
    for manifest in _catalog_manifests():
        decision = _evaluate_manifest_for_shell(manifest=manifest, shell="disabled")
        if not decision.skipped:
            continue
        reason = decision.reason or ""
        assert reason.startswith(f"skipped {manifest.id}:")
        assert "shell: disabled" in reason
        assert manifest.runtime in reason


# --------------------------------------------------------------------------- #
# The W0.4 steerability vector — a repo-provided binary must not stand in
# --------------------------------------------------------------------------- #


def test_repo_provided_binaries_are_refused_when_shell_disabled() -> None:
    assert _allow_repo_provided_binaries(shell="disabled") is False
    assert _allow_repo_provided_binaries(shell="restricted") is True
    assert _allow_repo_provided_binaries(shell="enabled") is True


def _plant_fake_binary(repo_root: Path, name: str) -> Path:
    bin_dir = repo_root / ".venv" / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    planted = bin_dir / name
    planted.write_text("#!/bin/sh\necho 0.0.0-pr-authored\n", encoding="utf-8")
    planted.chmod(planted.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return planted


def test_planted_repo_binary_wins_by_default_but_not_under_shell_disabled(
    tmp_path: Path,
) -> None:
    """The concrete attack W0.4 found, and the seam that closes it.

    ``resolve_analyzer()`` prefers ``<repo>/.venv/bin/<tool>`` over the pinned
    managed binary for *every* manifest, including ones that declare
    ``runtime: managed``. Under `shell: disabled` the PR head is untrusted
    content, so that preference has to be skipped.
    """
    manifest = _manifest(MANAGED_ANALYZER_ID)
    assert manifest.runtime == "managed"
    planted = _plant_fake_binary(tmp_path, manifest.command[0])
    assert os.access(planted, os.X_OK)

    default_plan = resolve_analyzer(manifest=manifest, repo_root=tmp_path, managed_available=True)
    assert default_plan.mode == "repo-native"
    assert default_plan.argv[0] == str(planted.resolve())

    hardened_plan = resolve_analyzer(
        manifest=manifest,
        repo_root=tmp_path,
        managed_available=True,
        repo_has_tool=False,
    )
    assert hardened_plan.mode == "managed"
    assert hardened_plan.argv[0] == manifest.command[0]
    assert str(planted.resolve()) not in hardened_plan.argv


# --------------------------------------------------------------------------- #
# Runtime wiring — the shell has to reach the pipeline and the adapter
# --------------------------------------------------------------------------- #


def test_pipeline_forwards_the_shell_to_the_adapter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A predicate nothing calls is the #96 failure mode. Pin the seam."""
    from mergecraft.analyzers import adapters, pipeline

    captured: list[dict[str, Any]] = []

    def _fake_run_adapter(**kwargs: Any) -> adapters.AdapterRunResult:
        captured.append(kwargs)
        return adapters.AdapterRunResult(findings=[], skipped=True, skip_reason="stubbed")

    monkeypatch.setattr(adapters, "run_adapter", _fake_run_adapter)
    monkeypatch.setattr(pipeline, "detect_enabled", lambda **_: [_manifest(MANAGED_ANALYZER_ID)])

    pipeline.run_analyzer_pipeline(
        repo_root=tmp_path,
        changed_files=["script.sh"],
        tier="untrusted",
        shell="disabled",
    )
    assert captured, "run_adapter was never reached"
    assert captured[0]["allow_repo_binaries"] is False

    captured.clear()
    pipeline.run_analyzer_pipeline(
        repo_root=tmp_path,
        changed_files=["script.sh"],
        tier="trusted",
        shell="restricted",
    )
    assert captured[0]["allow_repo_binaries"] is True


def test_pipeline_skips_repo_native_manifests_under_shell_disabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The named skip reaches the operator-visible status rows (D9).

    Tier is ``trusted`` here — a same-repo PR that still hardens with
    ``shell: disabled`` — so the shell axis is the one under test rather than
    the pre-existing tier axis.
    """
    from mergecraft.analyzers import adapters, pipeline

    def _unexpected(**_: Any) -> adapters.AdapterRunResult:
        msg = "a repo-native analyzer must not reach the adapter under shell: disabled"
        raise AssertionError(msg)

    monkeypatch.setattr(adapters, "run_adapter", _unexpected)
    monkeypatch.setattr(pipeline, "detect_enabled", lambda **_: [_manifest("ruff")])

    state = pipeline.run_analyzer_pipeline(
        repo_root=tmp_path,
        changed_files=["a.py"],
        tier="trusted",
        shell="disabled",
    )
    rows = {row.id: row for row in state.analyzers}
    assert rows["ruff"].status == "unavailable"
    assert "shell: disabled" in (rows["ruff"].reason or "")
    assert "repo-native" in (rows["ruff"].reason or "")


def test_tier_skip_wins_when_both_axes_apply(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two axes, one row: the tier reason is reported when both would skip."""
    from mergecraft.analyzers import adapters, pipeline

    monkeypatch.setattr(
        adapters,
        "run_adapter",
        lambda **_: adapters.AdapterRunResult(findings=[], skipped=True, skip_reason="unused"),
    )
    monkeypatch.setattr(pipeline, "detect_enabled", lambda **_: [_manifest("ruff")])

    state = pipeline.run_analyzer_pipeline(
        repo_root=tmp_path,
        changed_files=["a.py"],
        tier="untrusted",
        shell="disabled",
    )
    reason = state.analyzers[0].reason or ""
    assert "requires trusted tier" in reason


@pytest.mark.asyncio
async def test_run_analyzers_tool_passes_the_context_shell(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The MCP tool is the only door in; it must forward `ctx.payload.shell`."""
    import json

    from mergecraft.analyzers import pipeline
    from mergecraft.mcp.analyzers import run_analyzers_tool
    from mergecraft.mcp.tool_state import AnalyzerRunState

    seen: dict[str, Any] = {}

    def _fake_pipeline(**kwargs: Any) -> AnalyzerRunState:
        seen.update(kwargs)
        return AnalyzerRunState(ran=False, reason="stubbed")

    monkeypatch.setattr(pipeline, "run_analyzer_pipeline", _fake_pipeline)

    ctx = _ctx(tmp_path, shell="disabled", trigger="pull_request_target")
    result = await run_analyzers_tool(ctx).execute({"changed_files": []})
    json.loads(result.content[0]["text"])
    assert seen["shell"] == "disabled"


# --------------------------------------------------------------------------- #
# W1.4 / W1.5 / W1.6 — regression guards: nothing else moves
# --------------------------------------------------------------------------- #


def test_untrusted_tier_selection_unchanged() -> None:
    """W1.4: the tier axis is orthogonal to the shell axis and must not shift."""
    trusted_only = _manifest("ruff")
    assert trusted_only.trust == "trusted"
    decision = evaluate_manifest_for_tier(manifest=trusted_only, tier="untrusted")
    assert decision.skipped is True
    assert "requires trusted tier" in (decision.reason or "")

    untrusted_ok = _manifest(MANAGED_ANALYZER_ID)
    assert untrusted_ok.trust == "untrusted"
    assert evaluate_manifest_for_tier(manifest=untrusted_ok, tier="untrusted").skipped is False
    assert evaluate_manifest_for_tier(manifest=trusted_only, tier="trusted").skipped is False


def test_offline_diff_review_path_unchanged(tmp_path: Path) -> None:
    """W1.5: `trigger == "unknown"` is the operator's own tree — still enabled."""
    ctx = _ctx(tmp_path, shell="disabled", trigger="unknown", tier="trusted")
    assert analyzers_enabled(ctx) is True
    assert {"run_analyzers", "analyzer_findings"} <= _tool_names(ctx)


def test_analyzer_env_still_scrubbed_on_untrusted_runs(
    monkeypatch: pytest.MonkeyPatch, fork_pr_event: dict[str, object]
) -> None:
    """W1.6: widening *what runs* must not widen *what it sees*."""
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_shell_split_canary")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk_shell_split_canary")
    env = build_analyzer_env(
        event=fork_pr_event,
        tier="untrusted",
        repo_env={
            "GITHUB_TOKEN": "ghp_shell_split_canary",
            "ANTHROPIC_API_KEY": "sk_shell_split_canary",
            "PATH": "/usr/bin",
        },
    )
    joined = " ".join(f"{key}={value}" for key, value in env.items())
    assert "ghp_shell_split_canary" not in joined
    assert "sk_shell_split_canary" not in joined
    assert env.get("PATH") == "/usr/bin"
