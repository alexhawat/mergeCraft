"""Tests for the runtime seam that emits a packet from a finished run (#96).

These drive ``emit_run_packet`` against a realistic ``ToolContext`` — the
same object ``main()`` holds at end-of-run — and assert on the artifact that
lands on disk, not on the builder's return value. The defect these cover was
a missing *consumer*, so the assertions are about a file existing with real
content in it.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from mergecraft.analyzers.finding import make_finding
from mergecraft.evidence.packet import PACKET_SCHEMA_VERSION
from mergecraft.evidence.run_packet import (
    PreparedPacket,
    build_run_packet,
    changed_paths_from_diff,
    classify_run_blast_radius,
    emit_run_packet,
    resolve_packet_path,
)
from mergecraft.mcp.context import PayloadEvent, RepoIdentity, ResolvedPayload, ToolContext
from mergecraft.mcp.tool_state import (
    AnalyzerRunState,
    AnalyzerStatusRow,
    ApprovalRecord,
    init_tool_state,
    primary_repo_state,
)
from mergecraft.modes import compute_modes
from mergecraft.utils.github import GitHubClient

_MIGRATION_DIFF = """\
diff --git a/db/migrations/0007_drop_users.sql b/db/migrations/0007_drop_users.sql
new file mode 100644
--- /dev/null
+++ b/db/migrations/0007_drop_users.sql
@@ -0,0 +1,2 @@
+DROP TABLE users;
+ALTER TABLE accounts ADD COLUMN legacy boolean;
diff --git a/.github/workflows/ci.yml b/.github/workflows/ci.yml
--- a/.github/workflows/ci.yml
+++ b/.github/workflows/ci.yml
@@ -1,2 +1,3 @@
 name: ci
+on: [push]
diff --git a/uv.lock b/uv.lock
--- a/uv.lock
+++ b/uv.lock
@@ -1,2 +1,3 @@
 version = 1
+requires-python = ">=3.14"
"""

_TRIVIAL_DIFF = """\
diff --git a/README.md b/README.md
--- a/README.md
+++ b/README.md
@@ -1,2 +1,2 @@
 # demo
-old line
+new line
"""


def _make_ctx(
    tmp_path: Path,
    *,
    diff_text: str | None = _MIGRATION_DIFF,
    is_pr: bool = True,
    findings: list[dict[str, Any]] | None = None,
) -> ToolContext:
    """Build a ToolContext shaped like the one ``main()`` holds at end-of-run."""
    tool_state = init_tool_state(owner="acme", name="demo", dir=str(tmp_path))
    if diff_text is not None:
        diff_path = tmp_path / "pr-42.diff"
        diff_path.write_text(diff_text, encoding="utf-8")
        primary_repo_state(tool_state).diff_path = str(diff_path)
    tool_state.approval = ApprovalRecord(would_approve=True, sha="deadbeef")
    tool_state.analyzer_run = AnalyzerRunState(
        ran=True,
        analyzers=[AnalyzerStatusRow(id="ruff", status="completed", finding_count=1)],
        findings=findings if findings is not None else [_sample_finding()],
    )
    return ToolContext(
        agent_id="claude",
        repo=RepoIdentity(owner="acme", name="demo"),
        payload=ResolvedPayload(
            event=PayloadEvent(trigger="pull_request", issue_number=42, is_pr=is_pr),
        ),
        github=GitHubClient(token=""),
        github_installation_token="",
        git_token="",
        api_token="",
        modes=compute_modes("claude"),
        tool_state=tool_state,
        mcp_server_url="",
        tmpdir=str(tmp_path),
        resolved_model="claude-sonnet-4-5",
    )


def _sample_finding() -> dict[str, Any]:
    return make_finding(
        tool="ruff",
        rule_id="F401",
        category="Maintainability & Code Quality",
        severity="Minor",
        confidence="likely",
        message="unused import",
        path="db/migrations/0007_drop_users.sql",
        start_line=1,
        end_line=1,
        source="analyzer",
        introduced_by_pr="true",
    ).model_dump()


@pytest.fixture(autouse=True)
def _isolate_packet_dir(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep a stray RUNNER_TEMP / override from redirecting test artifacts."""
    monkeypatch.delenv("RUNNER_TEMP", raising=False)
    monkeypatch.delenv("MERGECRAFT_EVIDENCE_DIR", raising=False)


def test_emit_writes_a_packet_with_populated_blast_radius(tmp_path: Path) -> None:
    """The end-to-end artifact: a real file, with the section that was dead."""
    written = emit_run_packet(_make_ctx(tmp_path), run_succeeded=True)

    assert written is not None
    assert written.is_file(), "no packet reached disk — the emitter was not called"
    packet = json.loads(written.read_text(encoding="utf-8"))

    assert packet["schema_version"] == PACKET_SCHEMA_VERSION
    assert packet["change_id"] == "acme/demo#42"
    assert packet["blast_radius"] is not None, "blast_radius stayed None — classifier not consulted"
    assert packet["blast_radius"]["lane"] == "high"
    assert packet["blast_radius"]["auto_merge_lane"] == "forbidden"
    assert "migrations" in packet["blast_radius"]["categories"]
    assert packet["findings"], "analyzer findings did not reach the packet"
    assert packet["decision"] is not None
    assert packet["self_assessment"] == {"approved": True, "sha": "deadbeef"}


def test_files_changed_includes_scope_exception_paths(tmp_path: Path) -> None:
    """Workflows, migrations and lockfiles reach the packet via analyzers/scope."""
    written = emit_run_packet(_make_ctx(tmp_path), run_succeeded=True)
    assert written is not None
    packet = json.loads(written.read_text(encoding="utf-8"))

    assert set(packet["files_changed"]) == {
        ".github/workflows/ci.yml",
        "db/migrations/0007_drop_users.sql",
        "uv.lock",
    }


def test_deterministic_checks_carry_the_catalog_command(tmp_path: Path) -> None:
    """Analyzer rows become packet rows with the command that actually ran."""
    written = emit_run_packet(_make_ctx(tmp_path), run_succeeded=True)
    assert written is not None
    checks = json.loads(written.read_text(encoding="utf-8"))["deterministic_checks"]

    assert [check["name"] for check in checks] == ["ruff"]
    assert checks[0]["status"] == "completed"
    assert checks[0]["command"], "command must be recorded, not blank"


def test_failed_run_still_emits_a_packet(tmp_path: Path) -> None:
    """Evidence matters most when the run did not succeed."""
    written = emit_run_packet(_make_ctx(tmp_path), run_succeeded=False)

    assert written is not None
    decision = json.loads(written.read_text(encoding="utf-8"))["decision"]
    assert decision["verdict"] != "auto_merge"


def test_self_assessment_alone_never_yields_auto_merge(tmp_path: Path) -> None:
    """#41's hard rule survives the wiring: prose cannot outvote the evidence."""
    ctx = _make_ctx(tmp_path, diff_text=_TRIVIAL_DIFF, findings=[])
    written = emit_run_packet(ctx, run_succeeded=True)

    assert written is not None
    packet = json.loads(written.read_text(encoding="utf-8"))
    assert packet["self_assessment"]["approved"] is True
    assert packet["decision"]["verdict"] != "auto_merge"


def test_non_pr_run_emits_nothing(tmp_path: Path) -> None:
    """A run with no proposed merge has no change to attest to."""
    assert emit_run_packet(_make_ctx(tmp_path, is_pr=False), run_succeeded=True) is None


def test_emission_never_raises_into_the_run(tmp_path: Path) -> None:
    """A packet is an audit artifact; failing to write one cannot fail the run."""
    ctx = _make_ctx(tmp_path)
    ctx.tool_state.repos.clear()  # primary_repo_state() will raise

    assert emit_run_packet(ctx, run_succeeded=True) is None


def test_emit_run_packet_does_not_rebuild_when_packet_ready(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = _make_ctx(tmp_path)
    packet = build_run_packet(ctx, change_id="acme/demo#42", run_succeeded=True)
    calls = {"n": 0}

    def _boom(*args: object, **kwargs: object) -> None:
        calls["n"] += 1
        msg = "must not rebuild"
        raise RuntimeError(msg)

    monkeypatch.setattr("mergecraft.evidence.run_packet.build_run_packet", _boom)
    written = emit_run_packet(ctx, run_succeeded=True, packet=packet)
    assert calls["n"] == 0
    assert written is not None
    assert json.loads(written.read_text(encoding="utf-8"))["change_id"] == packet.change_id


def test_missing_diff_leaves_blast_radius_unset(tmp_path: Path) -> None:
    """No diff means no classification — not a fabricated 'low' lane."""
    written = emit_run_packet(_make_ctx(tmp_path, diff_text=None), run_succeeded=True)

    assert written is not None
    assert json.loads(written.read_text(encoding="utf-8"))["blast_radius"] is None


def test_explicit_change_id_and_output_path_are_honored(tmp_path: Path) -> None:
    """The offline path supplies both, having no PR and its own destination."""
    target = tmp_path / "nested" / "packet.json"
    written = emit_run_packet(
        _make_ctx(tmp_path, is_pr=False),
        run_succeeded=True,
        change_id="local/demo@origin/main",
        output_path=target,
    )

    assert written == target
    assert json.loads(target.read_text(encoding="utf-8"))["change_id"] == "local/demo@origin/main"


def test_extra_findings_merge_without_duplicating(tmp_path: Path) -> None:
    """Agent findings join analyzer findings, deduplicated by fingerprint."""
    duplicate = make_finding(**_sample_finding_kwargs())
    written = emit_run_packet(
        _make_ctx(tmp_path),
        run_succeeded=True,
        extra_findings=[duplicate],
    )

    assert written is not None
    findings = json.loads(written.read_text(encoding="utf-8"))["findings"]
    # Assert the dedup property itself rather than the packet's total, which
    # also carries trajectory findings since Batch C (#43).
    matches = [f for f in findings if f["fingerprint"] == duplicate.fingerprint]
    assert len(matches) == 1, "the same finding from two sources must not double-count"


def _sample_finding_kwargs() -> dict[str, Any]:
    return {
        "tool": "ruff",
        "rule_id": "F401",
        "category": "Maintainability & Code Quality",
        "severity": "Minor",
        "confidence": "likely",
        "message": "unused import",
        "path": "db/migrations/0007_drop_users.sql",
        "start_line": 1,
        "end_line": 1,
        "source": "analyzer",
        "introduced_by_pr": "true",
    }


class TestPacketPathResolution:
    """``resolve_packet_path`` must land outside the checkout and survive the step."""

    def test_prefers_the_explicit_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MERGECRAFT_EVIDENCE_DIR", "/tmp/override")
        monkeypatch.setenv("RUNNER_TEMP", "/tmp/runner")
        path = resolve_packet_path(tmpdir="/tmp/run", change_slug="acme-demo-42")
        assert path.parent == Path("/tmp/override")

    def test_falls_back_to_runner_temp(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("MERGECRAFT_EVIDENCE_DIR", raising=False)
        monkeypatch.setenv("RUNNER_TEMP", "/tmp/runner")
        path = resolve_packet_path(tmpdir="/tmp/run", change_slug="acme-demo-42")
        assert path.parent == Path("/tmp/runner/mergecraft")

    def test_falls_back_to_the_run_tmpdir(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("MERGECRAFT_EVIDENCE_DIR", raising=False)
        monkeypatch.delenv("RUNNER_TEMP", raising=False)
        path = resolve_packet_path(tmpdir="/tmp/run", change_slug="acme-demo-42")
        assert path.parent == Path("/tmp/run/evidence")


class TestActionOutputSurfacing:
    """The packet is worthless to an operator if its path never leaves the run.

    Retargeted (test-creator, W5 xfail reconciliation) from the dead
    ``action`` package's ``entry`` module (``_write_outputs``) onto the
    *live* entrypoint — ``action.yml`` -> ``docker-entrypoint.sh`` ->
    ``mergecraft gha`` -> ``cli/gha_cmd.py::_run_main`` (confirmed via
    ``action.yml``). W5.4 pinned the output value as the packet JSON body
    itself (heredoc-delimited), not the bare path the dead writer used — see
    ``cli/gha_cmd.py::_write_evidence_packet_output``.
    """

    def test_packet_path_is_written_to_github_output(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from mergecraft.cli.gha_cmd import _write_evidence_packet_output

        packet_path = tmp_path / "packet.json"
        packet_path.write_text('{"schema_version": "1.5.0"}', encoding="utf-8")
        output_file = tmp_path / "gh_output"
        monkeypatch.setenv("GITHUB_OUTPUT", str(output_file))

        _write_evidence_packet_output(str(packet_path))

        written = output_file.read_text(encoding="utf-8")
        assert "evidence_packet" in written
        assert '{"schema_version": "1.5.0"}' in written

    def test_absent_packet_omits_the_output(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A workflow must be able to gate on the output being set at all.

        Drives the real ``_run_main`` orchestration (not the writer in
        isolation) since the "no packet" case is ``_run_main`` choosing not
        to call ``_write_evidence_packet_output`` at all when
        ``MainResult.evidence_packet_path`` is falsy — that call-site
        decision is exactly what this test pins.
        """
        from mergecraft.cli.gha_cmd import _run_main
        from mergecraft.main import MainResult

        output_file = tmp_path / "gh_output"
        output_file.touch()
        monkeypatch.setenv("GITHUB_OUTPUT", str(output_file))

        async def _fake_main() -> MainResult:
            return MainResult(success=True, result="ok", evidence_packet_path=None)

        import mergecraft.main as main_mod

        monkeypatch.setattr(main_mod, "main", _fake_main)

        asyncio.run(_run_main())

        assert "evidence_packet" not in output_file.read_text(encoding="utf-8")

    def test_action_yml_declares_the_output(self) -> None:
        """The Python side writing the key is only half the Action contract."""
        import yaml

        action = yaml.safe_load(
            (Path(__file__).resolve().parents[2] / "action.yml").read_text(encoding="utf-8")
        )
        assert "evidence_packet" in action["outputs"]


class TestBlastRadiusFromDiff:
    """The classifier is fed from the analyzer scope parser, not a second one."""

    def test_empty_diff_classifies_to_nothing(self) -> None:
        assert classify_run_blast_radius("") is None

    def test_lockfile_change_is_detected(self) -> None:
        classification = classify_run_blast_radius(_MIGRATION_DIFF)
        assert classification is not None
        assert "dependency_changes" in classification.categories

    def test_changed_paths_are_deduplicated_and_sorted(self) -> None:
        paths = changed_paths_from_diff(_MIGRATION_DIFF)
        assert paths == sorted(set(paths))


class TestModePromptVersions:
    """S5 (#145) — the packet names the prompt that produced its verdict, not the catalog.

    The catalog (``ctx.modes``) carries every available mode; ``state.selected_mode``
    is the one the agent actually dispatched on. The packet must record the latter
    so an archived verdict is attributable to the prompt that produced it. These
    tests pin both branches so the catalog-vs-selected confusion the review found
    cannot regress.
    """

    def test_run_packet_emits_only_selected_mode(self, tmp_path: Path) -> None:
        """A run that selected ``Review`` records exactly one row, on the Review mode."""
        ctx = _make_ctx(tmp_path)
        # ``_make_ctx`` seeds a full ``compute_modes(...)`` catalog; mark just
        # the Review mode as dispatched. ``build_run_packet`` must ignore
        # every other mode in the catalog.
        ctx.tool_state.selected_mode = "Review"
        packet = build_run_packet(ctx, change_id="acme/demo#42", run_succeeded=True)

        versions = packet.mode_prompt_versions
        assert versions is not None
        assert len(versions) == 1, (
            f"expected one ModePromptVersion row, got {len(versions)} — "
            "ctx.modes (catalog) leaked into mode_prompt_versions"
        )
        only = versions[0]
        assert only.mode_name == "Review"
        # The version should match the catalog's Review mode version, not be
        # the empty string for "unknown catalog entry".
        expected_version = next(m.version for m in ctx.modes if m.name == "Review")
        assert only.prompt_version == expected_version

    def test_run_packet_no_selected_mode_yields_empty_field(self, tmp_path: Path) -> None:
        """A run with no selected mode emits an empty ``mode_prompt_versions`` list."""
        ctx = _make_ctx(tmp_path)
        assert ctx.tool_state.selected_mode is None  # _make_ctx leaves it unset
        packet = build_run_packet(ctx, change_id="acme/demo#42", run_succeeded=True)

        # An empty sequence is normalised to ``None`` at the packet wire
        # boundary (``build_packet`` and the existing schema contract); this
        # matches what the pre-S5 envelope returns when no mode ran.
        assert packet.mode_prompt_versions is None or (len(packet.mode_prompt_versions) == 0)


def test_merge_findings_empty_fingerprint_does_not_duplicate() -> None:
    """Empty fingerprints must not always append; use a stable fallback key."""
    from mergecraft.analyzers.finding import Finding
    from mergecraft.evidence.findings import merge_findings

    shared = {
        "tool": "agent",
        "rule_id": "X",
        "category": "Security & Privacy",
        "severity": "Major",
        "confidence": "certain",
        "message": "same issue",
        "path": "src/a.py",
        "start_line": 3,
        "end_line": 3,
        "fingerprint": "",
        "evidence": [],
        "remediation": None,
        "autofix": None,
        "introduced_by_pr": "true",
        "source": "agent",
        "cluster_id": None,
    }
    left = Finding.model_validate(shared)
    right = Finding.model_validate(shared)
    merged = merge_findings([left], [right])
    assert len(merged) == 1


def test_merge_findings_keeps_higher_severity_on_fingerprint_collision() -> None:
    """A Major/Critical CI row must not lose to an earlier Minor agent duplicate."""
    from mergecraft.analyzers.finding import make_finding
    from mergecraft.evidence.findings import merge_findings

    agent = make_finding(
        tool="agent",
        rule_id="F401",
        category="Maintainability & Code Quality",
        severity="Minor",
        confidence="certain",
        message="unused import",
        path="src/app.py",
        start_line=3,
        end_line=3,
        source="agent",
        fingerprint="same-fp",
    )
    ci = make_finding(
        tool="ruff",
        rule_id="F401",
        category="Maintainability & Code Quality",
        severity="Major",
        confidence="certain",
        message="unused import",
        path="src/app.py",
        start_line=3,
        end_line=3,
        source="ci",
        fingerprint="same-fp",
    )
    merged = merge_findings([agent], [ci])
    assert len(merged) == 1
    assert merged[0].severity == "Major"
    assert merged[0].source == "ci"


def test_load_run_findings_uses_typed_tool_state_not_getattr() -> None:
    import inspect

    from mergecraft.evidence.findings import load_run_findings

    source = inspect.getsource(load_run_findings)
    assert "getattr" not in source


def test_load_run_findings_keeps_ci_blocker_over_agent_minor(tmp_path: Path) -> None:
    from mergecraft.ci.evidence import record_ci_findings
    from mergecraft.evidence.findings import load_run_findings

    ctx = _make_ctx(tmp_path)
    agent = make_finding(
        tool="agent",
        rule_id="F401",
        category="Maintainability & Code Quality",
        severity="Minor",
        confidence="certain",
        message="unused import",
        path="src/app.py",
        start_line=3,
        end_line=3,
        source="agent",
        fingerprint="same-fp",
    )
    ci = make_finding(
        tool="ruff",
        rule_id="F401",
        category="Maintainability & Code Quality",
        severity="Critical",
        confidence="certain",
        message="unused import",
        path="src/app.py",
        start_line=3,
        end_line=3,
        source="ci",
        fingerprint="same-fp",
    )
    ctx.tool_state.agent_findings = [agent.model_dump()]
    record_ci_findings(ctx.tool_state, [ci])
    loaded = load_run_findings(ctx)
    matching = [item for item in loaded if item.fingerprint == "same-fp"]
    assert len(matching) == 1
    assert matching[0].severity == "Critical"
    assert matching[0].source == "ci"


def test_main_does_not_import_private_change_id() -> None:
    import inspect

    from mergecraft import main as main_mod

    source = inspect.getsource(main_mod)
    assert "_change_id" not in source
    assert "prepare_run_packet" in source


def test_emit_run_packet_skips_without_rebuild_when_prepared_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = _make_ctx(tmp_path)
    calls = {"n": 0}

    def _boom(*args: object, **kwargs: object) -> None:
        calls["n"] += 1
        msg = "must not rebuild"
        raise RuntimeError(msg)

    monkeypatch.setattr("mergecraft.evidence.run_packet.build_run_packet", _boom)
    assert emit_run_packet(ctx, run_succeeded=True, packet=PreparedPacket(None)) is None
    assert calls["n"] == 0


def test_deterministic_checks_unknown_id_is_keyerror_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mergecraft.evidence import run_packet as run_packet_mod

    ctx = _make_ctx(tmp_path)
    ctx.tool_state.analyzer_run = AnalyzerRunState(
        ran=True,
        analyzers=[AnalyzerStatusRow(id="not-a-catalog-tool", status="completed", finding_count=0)],
    )
    packet = build_run_packet(ctx, run_succeeded=True)
    names = {row.name: row.command for row in packet.deterministic_checks}
    assert names["not-a-catalog-tool"] == "not-a-catalog-tool"

    def _raise_os(*_args: object, **_kwargs: object) -> None:
        msg = "catalog unreadable"
        raise OSError(msg)

    monkeypatch.setattr("mergecraft.analyzers.registry.get_manifest", _raise_os)
    with pytest.raises(OSError, match="catalog unreadable"):
        run_packet_mod._deterministic_checks(ctx.tool_state)


def test_packet_helpers_use_tool_state_attributes_not_getattr() -> None:
    import inspect

    from mergecraft.evidence import run_packet as run_packet_mod
    from mergecraft.utils.status_checks import _catalog_unavailable_banner

    assert "getattr" not in inspect.getsource(run_packet_mod._deterministic_checks)
    assert "getattr" not in inspect.getsource(run_packet_mod._self_assessment)
    assert "getattr" not in inspect.getsource(run_packet_mod._read_diff_text)
    assert "getattr" not in inspect.getsource(_catalog_unavailable_banner)
