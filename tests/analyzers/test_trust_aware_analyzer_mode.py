"""#38 — trust-aware analyzer selection (Batch B, W3).

Batch A split the *shell* axis: under `shell: disabled` only manifests whose
argv mergeCraft ships are eligible. That leaves the second half of #38 open —
the `analyzers:` input itself is still trust-blind. It accepts exactly
`off | auto | full`, `resolve_analyzers_mode()` silently rewrites anything else
to `auto`, and nothing anywhere consults the mode when *selecting* manifests.

What #38 asks for is an `untrusted-only` mode meaning "run only analyzers that
are safe without secrets, without network, and without PR-authored command
construction" — the issue names both halves of that: `untrusted` **tier** and
`managed` **runtime**. So the mode applies two gates:

* the tier gate, evaluated as if the run were untrusted, so `trust: trusted`
  manifests skip with the reason `evaluate_manifest_for_tier()` already
  produces (D9 — one skip path, not a second vocabulary); and
* the runtime gate Batch A built for `shell: disabled`, so manifests needing
  repo-provided tooling skip even when the shell is merely `restricted`.

That second gate is what makes the mode more than a relabelling: on
`pull_request_target` with `shell: restricted`, today's tier gate alone still
admits repo-native manifests resolved against a PR-authored `.venv/bin`.

These cases pin:

* `untrusted-only` survives `resolve_analyzers_mode()` (W3.1);
* `auto` under an untrusted tier resolves to it (W3.2, D8);
* the full event x trust x mode matrix selects exactly the specified set (W3.3);
* skipped manifests are outcomes with reasons, never failures (W3.4);
* `full` on a trusted run is unchanged, and never *loosens* the tier gate on an
  untrusted one (W3.5);
* an unrecognised input fails safe to the more restrictive mode (W3.6); and
* the hardened example adopts the safe default explicitly (W3.7).
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from mergecraft.analyzers.registry import get_manifest, load_catalog
from mergecraft.analyzers.trust import (
    analyzers_enabled,
    derive_trust_tier,
    evaluate_manifest_for_tier,
)
from mergecraft.mcp.context import (
    PayloadEvent,
    RepoIdentity,
    ResolvedPayload,
    ToolContext,
)
from mergecraft.mcp.tool_state import init_tool_state
from mergecraft.modes import compute_modes
from mergecraft.utils.github import GitHubClient
from tests.analyzers.support import import_module

if TYPE_CHECKING:
    from mergecraft.analyzers.manifest import AnalyzerManifest

# W3.8 — RED until W4 lands the mode. Removed in the W4 commit.
pytestmark = pytest.mark.xfail(reason="green after W4 (#38)", strict=False)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# The mode axis under test. `off` short-circuits before the pipeline; the other
# three reach manifest selection.
MODES: tuple[str, ...] = ("off", "auto", "full", "untrusted-only")

# The issue's event axis. `offline` is the operator's own local diff review,
# which `derive_trust_tier(offline=True)` pins to `trusted`.
EVENTS: tuple[str, ...] = (
    "pull_request",
    "pull_request_target",
    "workflow_dispatch",
    "offline",
)

TIERS: tuple[str, ...] = ("trusted", "untrusted")

# Runtimes whose argv is copied verbatim out of a mergeCraft-shipped manifest.
# Spelled out here rather than imported so the matrix encodes the *policy* and
# would notice the production constant being widened.
SHIPPED_ARGV_RUNTIMES: frozenset[str] = frozenset({"managed", "container"})

# Analyzers that declare a `repo-native` runtime but execute in-process, with no
# subprocess and no repo-provided binary, so no repo tooling is required. See
# `resolve_analyzer()`'s special case and the W4 decision note.
IN_PROCESS_IDS: frozenset[str] = frozenset({"agentsec"})


# --------------------------------------------------------------------------- #
# Lazy accessors — the module must still collect before W4 adds the symbols.
# --------------------------------------------------------------------------- #


def _trust() -> Any:
    return import_module("mergecraft.analyzers.trust")


def _resolve_analyzers_mode(raw: str | None) -> Any:
    return _trust().resolve_analyzers_mode(raw)


def _resolve_effective_analyzers_mode(*, mode: str, tier: str) -> Any:
    return _trust().resolve_effective_analyzers_mode(mode=mode, tier=tier)


def _resolve_selection_tier(*, mode: str, tier: str) -> Any:
    return _trust().resolve_selection_tier(mode=mode, tier=tier)


def _evaluate_manifest_for_mode(*, manifest: AnalyzerManifest, mode: str) -> Any:
    return _trust().evaluate_manifest_for_mode(manifest=manifest, mode=mode)


def _catalog() -> list[AnalyzerManifest]:
    return sorted(load_catalog(), key=lambda m: m.id)


def _needs_repo_tooling(manifest: AnalyzerManifest) -> bool:
    """The runtime axis, restated from the policy rather than from the code."""
    if manifest.id in IN_PROCESS_IDS:
        return False
    return manifest.runtime not in SHIPPED_ARGV_RUNTIMES


def _ctx(
    tmp_path: Path,
    *,
    analyzers_mode: str,
    shell: str = "restricted",
    trigger: str = "pull_request",
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
        static_checks_enabled=False,
        analyzers_mode=analyzers_mode,  # type: ignore[arg-type]
        analyzers_settings_enabled=True,
        trust_tier=tier,  # type: ignore[arg-type]
    )


# --------------------------------------------------------------------------- #
# The specification the matrix asserts against.
# --------------------------------------------------------------------------- #


def _expected_selection(*, tier: str, mode: str, shell: str = "restricted") -> set[str]:
    """Restate #38's policy independently of the implementation.

    Written as a truth table over the two manifest attributes the policy reads
    (`trust`, `runtime`) so a drift in the production predicates fails here
    rather than being mirrored by it.
    """
    if mode == "off":
        return set()

    effective = "untrusted-only" if (mode == "auto" and tier == "untrusted") else mode
    # `full` must never *loosen* the tier gate on an untrusted run.
    selection_tier = "untrusted" if effective == "untrusted-only" or tier == "untrusted" else tier

    selected: set[str] = set()
    for manifest in _catalog():
        if selection_tier == "untrusted" and manifest.trust == "trusted":
            continue
        if _needs_repo_tooling(manifest) and (effective == "untrusted-only" or shell == "disabled"):
            continue
        selected.add(manifest.id)
    return selected


def _run_selection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    tier: str,
    mode: str,
    shell: str = "restricted",
) -> tuple[set[str], dict[str, Any]]:
    """Drive the real pipeline and report which manifests reached the adapter.

    Selection is observed at the adapter boundary rather than by re-calling the
    predicates, so a predicate that is correct but unwired still fails.
    """
    from mergecraft.analyzers import adapters, pipeline

    reached: set[str] = set()

    def _record(**kwargs: Any) -> adapters.AdapterRunResult:
        reached.add(str(kwargs["tool_id"]))
        return adapters.AdapterRunResult(findings=[])

    monkeypatch.setattr(adapters, "run_adapter", _record)
    monkeypatch.setattr(pipeline, "detect_enabled", lambda **_: _catalog())

    state = pipeline.run_analyzer_pipeline(
        repo_root=tmp_path,
        changed_files=["a.py", "b.sh", "c.tf", ".mcp.json"],
        tier=tier,  # type: ignore[arg-type]
        shell=shell,
        mode=mode,  # type: ignore[arg-type]
    )
    rows = {row.id: row for row in state.analyzers}
    return reached, rows


# --------------------------------------------------------------------------- #
# W3.1 — `untrusted-only` is a real input value
# --------------------------------------------------------------------------- #


def test_analyzers_input_accepts_untrusted_only() -> None:
    """#38's first acceptance box: the new value survives resolution."""
    assert _resolve_analyzers_mode("untrusted-only") == "untrusted-only"


@pytest.mark.parametrize("raw", ["UNTRUSTED-ONLY", "  untrusted-only  "])
def test_untrusted_only_is_normalised_like_the_other_values(raw: str) -> None:
    assert _resolve_analyzers_mode(raw) == "untrusted-only"


@pytest.mark.parametrize("raw", ["off", "auto", "full"])
def test_existing_mode_values_are_unchanged(raw: str) -> None:
    """Regression guard: the three shipped values keep resolving to themselves."""
    assert _resolve_analyzers_mode(raw) == raw


@pytest.mark.parametrize("raw", [None, "", "   "])
def test_unset_input_still_defaults_to_auto(raw: str | None) -> None:
    """An *absent* input is not ambiguous — it is the documented default."""
    assert _resolve_analyzers_mode(raw) == "auto"


# --------------------------------------------------------------------------- #
# W3.2 — `auto` implies trust-aware selection on untrusted events (D8)
# --------------------------------------------------------------------------- #


def test_auto_implies_trust_aware_under_pull_request_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D8's behaviour flip, derived from the tier rather than re-read from the event."""
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request_target")
    tier = derive_trust_tier(event={"pull_request": {}}, shell="restricted")
    assert tier == "untrusted"
    assert _resolve_effective_analyzers_mode(mode="auto", tier=tier) == "untrusted-only"


def test_auto_is_unchanged_on_trusted_runs() -> None:
    """The flip is scoped to untrusted runs; a same-repo PR still means `auto`."""
    assert _resolve_effective_analyzers_mode(mode="auto", tier="trusted") == "auto"


def test_auto_implies_trust_aware_on_fork_pull_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    """W4.2 reads `derive_trust_tier()`, so fork-head PRs get the same treatment."""
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
    tier = derive_trust_tier(
        event={"pull_request": {"head": {"repo": {"fork": True}}}},
        shell="restricted",
    )
    assert tier == "untrusted"
    assert _resolve_effective_analyzers_mode(mode="auto", tier=tier) == "untrusted-only"


def test_trusted_only_manifests_skip_under_auto_on_pull_request_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The end-to-end form of D8: named skips, not silent absence."""
    reached, rows = _run_selection(tmp_path, monkeypatch, tier="untrusted", mode="auto")

    trusted_only = {m.id for m in _catalog() if m.trust == "trusted"}
    assert not (trusted_only & reached)
    for analyzer_id in sorted(trusted_only):
        assert rows[analyzer_id].status == "unavailable"
        assert rows[analyzer_id].reason


# --------------------------------------------------------------------------- #
# W3.3 — the issue's explicit acceptance criterion: the full matrix
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("event", EVENTS)
@pytest.mark.parametrize("tier", TIERS)
@pytest.mark.parametrize("mode", MODES)
def test_event_trust_analyzers_matrix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    event: str,
    tier: str,
    mode: str,
) -> None:
    """Every cell of {4 events} x {2 tiers} x {4 modes}.

    Two of the eight event/tier pairs are unreachable in production
    (`workflow_dispatch` is always trusted, `pull_request_target` always
    untrusted) — they are asserted anyway as defence in depth, since the
    pipeline receives the tier as a parameter and must not depend on the event
    name to behave safely.
    """
    monkeypatch.setenv("GITHUB_EVENT_NAME", "" if event == "offline" else event)

    if mode == "off":
        ctx = _ctx(tmp_path, analyzers_mode=mode, tier=tier)
        assert analyzers_enabled(ctx) is False
        return

    reached, rows = _run_selection(tmp_path, monkeypatch, tier=tier, mode=mode)
    expected = _expected_selection(tier=tier, mode=mode)

    assert reached == expected

    # Everything the catalog offers but this cell excluded is a named skip.
    for analyzer_id in sorted({m.id for m in _catalog()} - expected):
        assert rows[analyzer_id].status == "unavailable"
        assert rows[analyzer_id].reason


@pytest.mark.parametrize(
    ("event", "expected_tier"),
    [
        ("pull_request_target", "untrusted"),
        ("workflow_dispatch", "trusted"),
        ("pull_request", "trusted"),
    ],
)
def test_event_axis_derives_the_expected_tier(
    monkeypatch: pytest.MonkeyPatch, event: str, expected_tier: str
) -> None:
    """Pin the event -> tier edge the matrix's tier axis stands on."""
    monkeypatch.setenv("GITHUB_EVENT_NAME", event)
    assert derive_trust_tier(event={"pull_request": {}}, shell="restricted") == expected_tier


def test_offline_event_is_trusted() -> None:
    assert derive_trust_tier(event=None, offline=True) == "trusted"


# --------------------------------------------------------------------------- #
# W3.4 — skips are outcomes, not failures (D9)
# --------------------------------------------------------------------------- #


def test_trusted_only_analyzers_skip_not_fail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A skipped manifest yields a row, never a failed run and never a gap."""
    reached, rows = _run_selection(tmp_path, monkeypatch, tier="trusted", mode="untrusted-only")

    catalog_ids = {m.id for m in _catalog()}
    assert set(rows) == catalog_ids, "every manifest must produce exactly one row"
    assert not any(row.status == "failed" for row in rows.values())
    for analyzer_id in sorted(catalog_ids - reached):
        assert rows[analyzer_id].status == "unavailable"


def test_mode_skip_reuses_the_existing_decision_shape() -> None:
    """D9: one skip vocabulary — the same dataclass the tier predicate returns."""
    decision = _evaluate_manifest_for_mode(manifest=get_manifest("ruff"), mode="untrusted-only")
    tier_decision = evaluate_manifest_for_tier(manifest=get_manifest("ruff"), tier="untrusted")
    assert type(decision) is type(tier_decision)
    assert decision.skipped is True
    assert decision.reason is not None
    assert "ruff" in decision.reason


def test_mode_predicate_is_inert_outside_untrusted_only() -> None:
    """Off the `untrusted-only` path the mode axis decides nothing."""
    for mode in ("auto", "full"):
        decision = _evaluate_manifest_for_mode(manifest=get_manifest("ruff"), mode=mode)
        assert decision.skipped is False


def test_skip_reason_names_the_axis_that_caused_it() -> None:
    """A reason that names the wrong cause is not a named reason (D9)."""
    decision = _evaluate_manifest_for_mode(manifest=get_manifest("ruff"), mode="untrusted-only")
    assert "untrusted-only" in (decision.reason or "")

    tier_decision = evaluate_manifest_for_tier(
        manifest=get_manifest("pylint"),
        tier="untrusted",
        cause="analyzers: untrusted-only",
    )
    assert tier_decision.skipped is True
    assert "untrusted-only" in (tier_decision.reason or "")


def test_default_tier_skip_reason_is_unchanged() -> None:
    """Regression guard: Batch A's reason string still renders for real fork PRs."""
    decision = evaluate_manifest_for_tier(manifest=get_manifest("pylint"), tier="untrusted")
    assert decision.skipped is True
    assert "fork PR / pull_request_target" in (decision.reason or "")


# --------------------------------------------------------------------------- #
# W3.5 — `full` is unchanged on trusted runs and never loosens untrusted ones
# --------------------------------------------------------------------------- #


def test_full_still_means_full_on_trusted_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression guard: the whole catalog is selected, as today."""
    reached, _ = _run_selection(tmp_path, monkeypatch, tier="trusted", mode="full")
    assert reached == {m.id for m in _catalog()}


def test_full_does_not_loosen_the_tier_gate_on_untrusted_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`full` is a *provisioning* request, never a trust override (convention 5)."""
    reached, _ = _run_selection(tmp_path, monkeypatch, tier="untrusted", mode="full")
    trusted_only = {m.id for m in _catalog() if m.trust == "trusted"}
    assert not (trusted_only & reached)


def test_selection_tier_never_relaxes_the_derived_tier() -> None:
    """No mode may turn an untrusted run into a trusted selection."""
    for mode in MODES:
        assert _resolve_selection_tier(mode=mode, tier="untrusted") == "untrusted"
    assert _resolve_selection_tier(mode="untrusted-only", tier="trusted") == "untrusted"
    assert _resolve_selection_tier(mode="full", tier="trusted") == "trusted"


# --------------------------------------------------------------------------- #
# W3.6 — unknown values fail safe (convention 5). Security-critical.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("raw", ["untrusted_only", "untrustedonly", "ful", "yes", "on", "true"])
def test_unknown_mode_value_falls_back_to_the_safer_mode(raw: str) -> None:
    """A typo must not silently buy the *wider* selection.

    Pre-change this returns `auto` for every one of these, which under
    `pull_request_target` is exactly the permissive reading #38 exists to close.
    """
    assert _resolve_analyzers_mode(raw) == "untrusted-only"


def test_unknown_mode_value_is_logged_not_swallowed() -> None:
    """Failing safe silently is still a silent failure — the operator is told."""
    from loguru import logger

    records: list[str] = []
    sink_id = logger.add(lambda message: records.append(message), level="WARNING")
    try:
        _resolve_analyzers_mode("untrusted_only")
    finally:
        logger.remove(sink_id)

    assert any("untrusted_only" in record for record in records)


def test_unknown_mode_value_is_not_more_permissive_than_auto_anywhere(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The fallback must be a subset of `auto`'s selection on every tier."""
    fallback = _resolve_analyzers_mode("nonsense-value")
    for tier in TIERS:
        fallback_selected, _ = _run_selection(tmp_path, monkeypatch, tier=tier, mode=fallback)
        auto_selected, _ = _run_selection(tmp_path, monkeypatch, tier=tier, mode="auto")
        assert fallback_selected <= auto_selected


# --------------------------------------------------------------------------- #
# W3.7 — the hardened example adopts the safe default
# --------------------------------------------------------------------------- #


def test_hardened_example_uses_the_safe_default() -> None:
    """#38's third acceptance box, asserted on the rendered workflow."""
    rendered = (REPO_ROOT / "examples" / "workflows" / "mergecraft-hardened.yml").read_text(
        encoding="utf-8"
    )
    assert "analyzers: untrusted-only" in rendered


def test_hardened_template_and_render_agree() -> None:
    """The template is the source of truth; `make example-workflows-check` gates drift."""
    template = (REPO_ROOT / "scripts" / "example_workflows" / "hardened.yml.tpl").read_text(
        encoding="utf-8"
    )
    assert "analyzers: untrusted-only" in template


def test_action_yml_documents_the_new_value() -> None:
    """W4.4: an input value nobody can discover is not an input value."""
    action = (REPO_ROOT / "action.yml").read_text(encoding="utf-8")
    assert "untrusted-only" in action


# --------------------------------------------------------------------------- #
# The `agentsec` allowance (W4 decision — see the wave plan's W0.4 follow-up)
# --------------------------------------------------------------------------- #


def test_agentsec_is_eligible_despite_declaring_repo_native() -> None:
    """It runs in-process: no subprocess, no repo binary, nothing PR-authored runs."""
    manifest = get_manifest("agentsec")
    assert manifest.runtime == "repo-native"
    assert manifest.trust == "untrusted"

    trust = _trust()
    assert trust.evaluate_manifest_for_shell(manifest=manifest, shell="disabled").skipped is False
    assert _evaluate_manifest_for_mode(manifest=manifest, mode="untrusted-only").skipped is False


def test_in_process_allowlist_matches_the_resolver(tmp_path: Path) -> None:
    """Drift guard: every allowlisted id must really bypass repo-binary resolution.

    If `resolve_analyzer()`'s special case is ever removed, the allowlist stops
    being true and this fails rather than quietly admitting a repo-native tool.
    """
    from mergecraft.analyzers.resolve import resolve_analyzer

    for analyzer_id in sorted(_trust().IN_PROCESS_ANALYZER_IDS):
        plan = resolve_analyzer(
            manifest=get_manifest(analyzer_id),
            repo_root=tmp_path,
            allow_repo_binaries=False,
        )
        assert plan.mode != "skip", f"{analyzer_id} must resolve without repo-provided tooling"


def test_no_other_repo_native_manifest_is_admitted() -> None:
    """The allowlist stays a narrow exception, not a hole in the runtime axis."""
    trust = _trust()
    for manifest in _catalog():
        if manifest.runtime in SHIPPED_ARGV_RUNTIMES or manifest.id in IN_PROCESS_IDS:
            continue
        assert (
            trust.evaluate_manifest_for_shell(manifest=manifest, shell="disabled").skipped is True
        )
        assert _evaluate_manifest_for_mode(manifest=manifest, mode="untrusted-only").skipped is True


# --------------------------------------------------------------------------- #
# Wiring — the mode must actually reach selection (issue #96 class of bug)
# --------------------------------------------------------------------------- #


def test_mcp_run_analyzers_passes_the_context_mode_to_the_pipeline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A correct predicate nobody calls is the bug `test_runtime_call_sites` exists for."""
    import asyncio

    from mergecraft.analyzers import pipeline
    from mergecraft.mcp.analyzers import run_analyzers_tool
    from mergecraft.mcp.tool_state import AnalyzerRunState

    seen: dict[str, Any] = {}

    def _capture(**kwargs: Any) -> AnalyzerRunState:
        seen.update(kwargs)
        return AnalyzerRunState(ran=False, reason="stubbed")

    monkeypatch.setattr(pipeline, "run_analyzer_pipeline", _capture)

    ctx = _ctx(tmp_path, analyzers_mode="untrusted-only", tier="untrusted")
    spec = run_analyzers_tool(ctx)
    asyncio.run(spec.execute({"repo_root": str(tmp_path), "changed_files": ["a.py"]}))

    assert seen.get("mode") == "untrusted-only"
