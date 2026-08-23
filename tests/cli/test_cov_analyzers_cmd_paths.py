"""Decision-path coverage for ``mergecraft analyzers`` (issue #431).

Drives the arms of ``cli/analyzers_cmd.py`` the existing suite never reaches:
the ``git diff`` probe's failure modes, the "no changed files" guards on
``detect`` / ``run`` / ``export``, the ``--sarif`` vs ``--output`` mutual
requirement, skipped-adapter bails, the optional ``explain`` rows, and every
branch of ``lock``'s platform derivation, reuse/refresh, and per-tool skips.

No test here runs a real analyzer, shells out to ``git``, or writes into the
checkout: ``run_adapter``/``resolve_with_lock``/``write_analyzers_doc`` are
stubbed and every path is under ``tmp_path``.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from typer.testing import CliRunner

from mergecraft.analyzers.adapters import AdapterRunResult
from mergecraft.analyzers.finding import make_finding
from mergecraft.analyzers.lockfile import LockEntry
from mergecraft.cli import analyzers_cmd
from mergecraft.cli.app import app
from mergecraft.cli.exits import CLI_CONFIGURATION_EXIT_CODE

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch

runner = CliRunner()

_ANSI = re.compile(r"\x1b\[[0-9;]*m")
# Rich wraps at the terminal width; pin it wide so table rows stay on one line.
_WIDE = {"COLUMNS": "200", "TERM": "dumb"}


def _plain(result: Any) -> str:
    return _ANSI.sub("", result.stdout + result.stderr)


def _plain_oneline(result: Any) -> str:
    return _plain(result).replace("\n", "")


def _row(text: str, analyzer_id: str) -> list[str]:
    """Return the rendered table row cells whose first cell is ``analyzer_id``."""
    for line in text.splitlines():
        cells = [cell.strip() for cell in line.split("\u2502")]
        if len(cells) > 1 and cells[1] == analyzer_id:
            return cells[1:-1]
    pytest.fail(f"no table row for {analyzer_id!r} in:\n{text}")


def _finding(path: str, line: int | None, message: str) -> Any:
    return make_finding(
        tool="ruff",
        rule_id="E501",
        category="Maintainability & Code Quality",
        severity="Minor",
        confidence="likely",
        message=message,
        path=path,
        start_line=line,
        end_line=line,
        source="analyzer",
    )


# ---------------------------------------------------------------------------
# _git_changed_files — every way the probe can come back empty
# ---------------------------------------------------------------------------


def test_git_probe_returns_nothing_when_git_is_not_installed(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    def _boom(*_args: Any, **_kwargs: Any) -> Any:
        raise OSError("git: no such file")

    monkeypatch.setattr(analyzers_cmd.subprocess, "run", _boom)
    assert analyzers_cmd._git_changed_files(tmp_path) == []


def test_git_probe_returns_nothing_on_a_non_zero_exit(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    """``git diff`` outside a repository exits 128 — its stdout must be ignored."""
    completed = subprocess.CompletedProcess(
        args=["git"], returncode=128, stdout="fatal: not a git repository\n", stderr=""
    )
    monkeypatch.setattr(analyzers_cmd.subprocess, "run", lambda *a, **k: completed)
    assert analyzers_cmd._git_changed_files(tmp_path) == []


def test_git_probe_strips_blank_lines_and_whitespace(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    completed = subprocess.CompletedProcess(
        args=["git"], returncode=0, stdout="src/a.py\n\n  src/b.py  \n\n", stderr=""
    )
    monkeypatch.setattr(analyzers_cmd.subprocess, "run", lambda *a, **k: completed)
    assert analyzers_cmd._git_changed_files(tmp_path) == ["src/a.py", "src/b.py"]


# ---------------------------------------------------------------------------
# analyzers list
# ---------------------------------------------------------------------------


def test_list_marks_an_analyzer_that_would_enable_for_the_changed_files(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    monkeypatch.setattr(analyzers_cmd, "_git_changed_files", lambda _dir: ["a.py"])
    result = runner.invoke(app, ["analyzers", "list", "--cwd", str(tmp_path)], env=_WIDE)
    text = _plain(result)
    assert result.exit_code == 0, text
    assert _row(text, "bandit") == ["bandit", "security", "auto", "yes"]
    # An analyzer whose detect globs do not match must stay on the "no" side.
    assert _row(text, "actionlint") == ["actionlint", "ci", "auto", "no"]


def test_list_falls_back_to_the_whole_tree_when_git_reports_no_changes(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    """The ``or ["."]`` fallback: nothing matches, so every row says "no"."""
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    monkeypatch.setattr(analyzers_cmd, "_git_changed_files", lambda _dir: [])
    result = runner.invoke(app, ["analyzers", "list", "--cwd", str(tmp_path)], env=_WIDE)
    text = _plain(result)
    assert result.exit_code == 0, text
    assert _row(text, "bandit") == ["bandit", "security", "auto", "no"]


# ---------------------------------------------------------------------------
# analyzers detect
# ---------------------------------------------------------------------------


def test_detect_bails_when_there_is_nothing_to_analyze(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(analyzers_cmd, "_git_changed_files", lambda _dir: [])
    result = runner.invoke(app, ["analyzers", "detect", "--cwd", str(tmp_path)], env=_WIDE)
    assert result.exit_code == CLI_CONFIGURATION_EXIT_CODE
    assert "pass --file or run inside a git repo" in _plain(result)


def test_detect_prints_id_category_and_runtime_for_explicit_files(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    result = runner.invoke(
        app,
        ["analyzers", "detect", "--cwd", str(tmp_path), "--file", "a.py"],
        env=_WIDE,
    )
    text = _plain(result)
    assert result.exit_code == 0, text
    assert "bandit (security, repo-native)" in text
    assert "actionlint" not in text


# ---------------------------------------------------------------------------
# analyzers run
# ---------------------------------------------------------------------------


def _stub_adapter(monkeypatch: MonkeyPatch, result: AdapterRunResult) -> dict[str, Any]:
    seen: dict[str, Any] = {}

    def _run(**kwargs: Any) -> AdapterRunResult:
        seen.update(kwargs)
        return result

    monkeypatch.setattr(analyzers_cmd, "run_adapter", _run)
    return seen


def test_run_bails_without_changed_files(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(analyzers_cmd, "_git_changed_files", lambda _dir: [])
    result = runner.invoke(app, ["analyzers", "run", "ruff", "--cwd", str(tmp_path)], env=_WIDE)
    assert result.exit_code == CLI_CONFIGURATION_EXIT_CODE
    assert "no changed files" in _plain(result)


def test_run_surfaces_the_adapters_skip_reason(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    _stub_adapter(
        monkeypatch,
        AdapterRunResult(findings=[], skipped=True, skip_reason="ruff not installed"),
    )
    result = runner.invoke(
        app, ["analyzers", "run", "ruff", "--cwd", str(tmp_path), "-f", "a.py"], env=_WIDE
    )
    assert result.exit_code == CLI_CONFIGURATION_EXIT_CODE
    assert "ruff not installed" in _plain(result)


def test_run_falls_back_to_a_generic_message_when_the_skip_has_no_reason(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    _stub_adapter(monkeypatch, AdapterRunResult(findings=[], skipped=True, skip_reason=None))
    result = runner.invoke(
        app, ["analyzers", "run", "ruff", "--cwd", str(tmp_path), "-f", "a.py"], env=_WIDE
    )
    assert result.exit_code == CLI_CONFIGURATION_EXIT_CODE
    assert "skipped ruff" in _plain(result)


def test_run_prints_the_version_note_and_anchors_findings(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    seen = _stub_adapter(
        monkeypatch,
        AdapterRunResult(
            findings=[
                _finding("src/a.py", 12, "line too long"),
                _finding("src/b.py", None, "file"),
            ],
            version_note="ruff 0.15.22 (repo-provided)",
        ),
    )
    result = runner.invoke(
        app, ["analyzers", "run", "ruff", "--cwd", str(tmp_path), "-f", "src/a.py"], env=_WIDE
    )
    text = _plain(result)
    assert result.exit_code == 0, text
    assert "findings: 2" in text
    assert "ruff 0.15.22 (repo-provided)" in text
    assert "src/a.py:12 [Minor] line too long" in text
    # No start line → the anchor is the bare path, with no trailing colon.
    assert "src/b.py [Minor] file" in text
    assert seen["changed_files"] == ["src/a.py"]
    assert seen["tier"] == "trusted"


def test_run_prints_at_most_twenty_findings(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    findings = [_finding("src/a.py", n, f"issue {n}") for n in range(1, 26)]
    _stub_adapter(monkeypatch, AdapterRunResult(findings=findings, version_note=None))
    result = runner.invoke(
        app, ["analyzers", "run", "ruff", "--cwd", str(tmp_path), "-f", "src/a.py"], env=_WIDE
    )
    text = _plain(result)
    assert result.exit_code == 0, text
    assert "findings: 25" in text
    assert "issue 20" in text
    assert "issue 21" not in text


# ---------------------------------------------------------------------------
# analyzers explain
# ---------------------------------------------------------------------------


def test_explain_rejects_an_unknown_analyzer_id() -> None:
    result = runner.invoke(app, ["analyzers", "explain", "not-a-tool"], env=_WIDE)
    assert result.exit_code == CLI_CONFIGURATION_EXIT_CODE
    assert "unknown analyzer id: 'not-a-tool'" in _plain(result)


def test_explain_prints_the_optional_rows_only_when_the_manifest_sets_them() -> None:
    ruff = _plain(runner.invoke(app, ["analyzers", "explain", "ruff"], env=_WIDE))
    assert "id: ruff" in ruff
    assert "parser: ruff_json" in ruff
    assert "runtime: repo-native" in ruff
    assert "trust: trusted" in ruff
    assert "exclusive_group: python-lint" in ruff
    assert "declared_unavailable:" not in ruff

    fortitude = _plain(runner.invoke(app, ["analyzers", "explain", "fortitude"], env=_WIDE))
    assert "declared_unavailable: manifest-only" in fortitude
    assert "exclusive_group:" not in fortitude

    actionlint = _plain(runner.invoke(app, ["analyzers", "explain", "actionlint"], env=_WIDE))
    # No languages declared → the em-dash placeholder, not an empty line.
    assert "languages: —" in actionlint
    assert "exclusive_group:" not in actionlint
    assert "declared_unavailable:" not in actionlint


# ---------------------------------------------------------------------------
# analyzers export
# ---------------------------------------------------------------------------


def test_export_requires_one_of_sarif_or_output(tmp_path: Path) -> None:
    result = runner.invoke(app, ["analyzers", "export", "ruff", "--cwd", str(tmp_path)], env=_WIDE)
    assert result.exit_code == CLI_CONFIGURATION_EXIT_CODE
    assert "pass --sarif or --output" in _plain(result)


def test_export_bails_without_changed_files(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(analyzers_cmd, "_git_changed_files", lambda _dir: [])
    result = runner.invoke(
        app, ["analyzers", "export", "ruff", "--cwd", str(tmp_path), "--sarif"], env=_WIDE
    )
    assert result.exit_code == CLI_CONFIGURATION_EXIT_CODE
    assert "no changed files" in _plain(result)


def test_export_bails_when_the_adapter_skipped(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    _stub_adapter(
        monkeypatch, AdapterRunResult(findings=[], skipped=True, skip_reason="no python files")
    )
    result = runner.invoke(
        app,
        ["analyzers", "export", "ruff", "--cwd", str(tmp_path), "--sarif", "-f", "a.py"],
        env=_WIDE,
    )
    assert result.exit_code == CLI_CONFIGURATION_EXIT_CODE
    assert "no python files" in _plain(result)


def test_export_sarif_goes_to_stdout_when_no_output_path_is_given(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    _stub_adapter(monkeypatch, AdapterRunResult(findings=[_finding("src/a.py", 3, "bad")]))
    result = runner.invoke(
        app,
        ["analyzers", "export", "ruff", "--cwd", str(tmp_path), "--sarif", "-f", "src/a.py"],
        env=_WIDE,
    )
    assert result.exit_code == 0, _plain(result)
    document = json.loads(result.stdout)
    assert document["version"] == "2.1.0"
    result_row = document["runs"][0]["results"][0]
    assert result_row["ruleId"] == "E501"
    assert result_row["message"]["text"] == "bad"


def test_export_output_path_writes_the_file_and_keeps_stdout_clean(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    """``--output`` alone satisfies the guard, and the payload lands on disk."""
    _stub_adapter(monkeypatch, AdapterRunResult(findings=[_finding("src/a.py", 3, "bad")]))
    out = tmp_path / "out.sarif"
    result = runner.invoke(
        app,
        [
            "analyzers",
            "export",
            "ruff",
            "--cwd",
            str(tmp_path),
            "-o",
            str(out),
            "-f",
            "src/a.py",
        ],
        env=_WIDE,
    )
    assert result.exit_code == 0, _plain(result)
    assert f"wrote {out}" in _plain_oneline(result)
    payload = out.read_text(encoding="utf-8")
    assert payload.endswith("\n")
    assert json.loads(payload)["runs"][0]["results"][0]["message"]["text"] == "bad"
    assert "2.1.0" not in result.stdout


# ---------------------------------------------------------------------------
# analyzers lock
# ---------------------------------------------------------------------------


class _FakeManifest:
    """Minimal stand-in exposing only the fields ``lock_cmd`` reads."""

    def __init__(
        self,
        analyzer_id: str,
        *,
        runtime: str,
        provenance: dict[str, str] | None = None,
        declared_unavailable: str | None = None,
        version: str = "1.0.0",
    ) -> None:
        self.id = analyzer_id
        self.runtime = runtime
        self.provenance = provenance or {}
        self.declared_unavailable = declared_unavailable
        self.version = version


def _stub_lock_world(
    monkeypatch: MonkeyPatch,
    *,
    catalog: list[_FakeManifest],
    existing: list[LockEntry] | None = None,
    resolve: Any = None,
) -> dict[str, Any]:
    captured: dict[str, Any] = {}

    def _write(path: Path, entries: list[Any], *, merge: bool = False) -> None:
        captured["path"] = path
        captured["entries"] = entries
        captured["merge"] = merge

    monkeypatch.setattr(analyzers_cmd, "load_catalog", lambda: list(catalog))
    monkeypatch.setattr(analyzers_cmd, "read_lock", lambda _path: list(existing or []))
    monkeypatch.setattr(analyzers_cmd, "write_lock", _write)
    if resolve is not None:
        monkeypatch.setattr(analyzers_cmd, "resolve_with_lock", resolve)
    return captured


class _Resolved:
    def __init__(self, source: str, sha256: str) -> None:
        self.source = source
        self.sha256 = sha256


def test_lock_skips_repo_native_and_declared_unavailable_tools(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    captured = _stub_lock_world(
        monkeypatch,
        catalog=[
            _FakeManifest("ruff", runtime="repo-native"),
            _FakeManifest("fortitude", runtime="managed", declared_unavailable="not bundled"),
            _FakeManifest("infer", runtime="container", version="2.3"),
        ],
    )
    result = runner.invoke(app, ["analyzers", "lock", "--cwd", str(tmp_path)], env=_WIDE)
    text = _plain(result)
    assert result.exit_code == 0, text
    entries = captured["entries"]
    assert [entry.tool_id for entry in entries] == ["infer"]
    assert entries[0].mode == "container"
    assert entries[0].source == "container:infer:2.3"
    assert entries[0].sha256 == "container"
    assert captured["path"] == tmp_path / ".mergecraft" / "analyzers.lock"
    assert captured["merge"] is True
    assert "lockfile updated" in text
    assert "(1 tools)" in text


def test_lock_reuses_an_existing_entry_unless_refresh_is_passed(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    pinned = LockEntry(
        tool_id="semgrep", version="0.0.1", mode="managed", source="old-url", sha256="old-sha"
    )
    catalog = [
        _FakeManifest(
            "semgrep", runtime="managed", provenance={"linux-amd64": "url"}, version="9.9"
        )
    ]
    resolved = _Resolved("new-url", "new-sha")

    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(analyzers_cmd, "load_catalog", lambda: list(catalog))

    captured = _stub_lock_world(
        monkeypatch,
        catalog=catalog,
        existing=[pinned],
        resolve=lambda **_kwargs: resolved,
    )
    import platform as platform_mod

    monkeypatch.setattr(platform_mod, "machine", lambda: "x86_64")

    reused = runner.invoke(app, ["analyzers", "lock", "--cwd", str(tmp_path)], env=_WIDE)
    assert reused.exit_code == 0, _plain(reused)
    assert captured["entries"] == [pinned]

    refreshed = runner.invoke(
        app, ["analyzers", "lock", "--cwd", str(tmp_path), "--refresh"], env=_WIDE
    )
    assert refreshed.exit_code == 0, _plain(refreshed)
    entry = captured["entries"][0]
    assert (entry.tool_id, entry.version, entry.source, entry.sha256) == (
        "semgrep",
        "9.9",
        "new-url",
        "new-sha",
    )
    assert captured["merge"] is False


def test_lock_skips_a_tool_with_no_provenance_for_this_platform(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    """The derived platform key gates provenance — only the matching tool locks."""
    import platform as platform_mod

    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(platform_mod, "machine", lambda: "aarch64")
    captured = _stub_lock_world(
        monkeypatch,
        catalog=[
            _FakeManifest("arm-only", runtime="managed", provenance={"linux-arm64": "u"}),
            _FakeManifest("amd-only", runtime="managed", provenance={"linux-amd64": "u"}),
        ],
        resolve=lambda **_kwargs: _Resolved("u", "sha"),
    )
    result = runner.invoke(app, ["analyzers", "lock", "--cwd", str(tmp_path)], env=_WIDE)
    assert result.exit_code == 0, _plain(result)
    assert [entry.tool_id for entry in captured["entries"]] == ["arm-only"]


def test_lock_derives_the_darwin_platform_key_from_the_machine_arch(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    import platform as platform_mod

    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(platform_mod, "machine", lambda: "x86_64")
    captured = _stub_lock_world(
        monkeypatch,
        catalog=[
            _FakeManifest("mac-intel", runtime="managed", provenance={"darwin-amd64": "u"}),
            _FakeManifest("mac-arm", runtime="managed", provenance={"darwin-arm64": "u"}),
        ],
        resolve=lambda **_kwargs: _Resolved("u", "sha"),
    )
    result = runner.invoke(app, ["analyzers", "lock", "--cwd", str(tmp_path)], env=_WIDE)
    assert result.exit_code == 0, _plain(result)
    assert [entry.tool_id for entry in captured["entries"]] == ["mac-intel"]

    monkeypatch.setattr(platform_mod, "machine", lambda: "ARM64")
    result = runner.invoke(app, ["analyzers", "lock", "--cwd", str(tmp_path)], env=_WIDE)
    assert result.exit_code == 0, _plain(result)
    assert [entry.tool_id for entry in captured["entries"]] == ["mac-arm"]


def test_lock_warns_and_continues_when_provisioning_one_tool_fails(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    import platform as platform_mod

    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(platform_mod, "machine", lambda: "x86_64")

    def _resolve(*, manifest: Any, **_kwargs: Any) -> _Resolved:
        if manifest.id == "broken":
            msg = "checksum mismatch"
            raise RuntimeError(msg)
        return _Resolved("good-url", "good-sha")

    captured = _stub_lock_world(
        monkeypatch,
        catalog=[
            _FakeManifest("broken", runtime="managed", provenance={"linux-amd64": "u"}),
            _FakeManifest("healthy", runtime="managed", provenance={"linux-amd64": "u"}),
        ],
        resolve=_resolve,
    )
    result = runner.invoke(app, ["analyzers", "lock", "--cwd", str(tmp_path)], env=_WIDE)
    text = _plain(result)
    assert result.exit_code == 0, text
    assert "skip broken: checksum mismatch" in text
    assert [entry.tool_id for entry in captured["entries"]] == ["healthy"]


# ---------------------------------------------------------------------------
# analyzers docs
# ---------------------------------------------------------------------------


def test_docs_reports_the_path_the_generator_wrote(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    generated = tmp_path / "ANALYZERS.md"
    monkeypatch.setattr(analyzers_cmd, "write_analyzers_doc", lambda: generated)
    result = runner.invoke(app, ["analyzers", "docs"], env=_WIDE)
    assert result.exit_code == 0, _plain(result)
    assert f"wrote {generated}" in _plain_oneline(result)
