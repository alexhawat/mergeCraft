"""Tests for the runtime seam that emits a packet from a finished run (#96).

These drive ``emit_run_packet`` against a realistic ``ToolContext`` — the
same object ``main()`` holds at end-of-run — and assert on the artifact that
lands on disk, not on the builder's return value. The defect these cover was
a missing *consumer*, so the assertions are about a file existing with real
content in it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from mergecraft.analyzers.finding import make_finding
from mergecraft.evidence.packet import PACKET_SCHEMA_VERSION
from mergecraft.evidence.run_packet import (
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
    assert len(findings) == 1, "the same finding from two sources must not double-count"


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
    """The packet is worthless to an operator if its path never leaves the run."""

    def test_packet_path_is_written_to_github_output(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from mergecraft.action.entry import _write_outputs
        from mergecraft.main import MainResult

        output_file = tmp_path / "gh_output"
        monkeypatch.setenv("GITHUB_OUTPUT", str(output_file))
        _write_outputs(
            MainResult(success=True, result="ok", evidence_packet_path="/tmp/packet.json")
        )

        written = output_file.read_text(encoding="utf-8")
        assert "evidence_packet=/tmp/packet.json\n" in written
        assert "result=ok\n" in written

    def test_absent_packet_omits_the_output(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A workflow must be able to gate on the output being set at all."""
        from mergecraft.action.entry import _write_outputs
        from mergecraft.main import MainResult

        output_file = tmp_path / "gh_output"
        monkeypatch.setenv("GITHUB_OUTPUT", str(output_file))
        _write_outputs(MainResult(success=True, result="ok", evidence_packet_path=None))

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
