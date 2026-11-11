"""Untrusted-tier scanners take rules and config from mergeCraft, not the reviewed tree.

Also covers the trusted-tier version probe: it runs through the analyzer spawn
path with the scrubbed environment.
"""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from mergecraft.analyzers import pipeline
from mergecraft.analyzers.contracts import run_differential_adapter
from mergecraft.analyzers.detect import find_repo_binary
from mergecraft.analyzers.execution import (
    SCANNER_CONFIG_RULE_ID,
    finalize_plan,
    neutral_config_dir,
    provision_platform_key,
    scanner_config_change_findings,
)
from mergecraft.analyzers.pattern import prepare_pattern_plan
from mergecraft.analyzers.registry import get_manifest
from mergecraft.analyzers.resolve import AnalyzerPlan, resolve_analyzer

if TYPE_CHECKING:
    from mergecraft.analyzers.manifest import TrustTier

_CATALOG = Path(__file__).resolve().parents[2] / "src" / "mergecraft" / "analyzers" / "catalog"
#: The operator's managed-binary cache, read at import: the hermetic fixture points
#: ``XDG_CACHE_HOME`` at an empty per-test directory, and the real-tool tests below
#: only use a pinned binary that is already cached (they never download one).
_OPERATOR_CACHE = (
    Path(os.environ.get("XDG_CACHE_HOME") or (Path.home() / ".cache"))
    / "mergecraft"
    / "analyzer-cache"
)
_GIT = ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", "-c", "commit.gpgsign=false"]


@pytest.fixture(autouse=True)
def _isolated_git_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        [*_GIT, "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def _pr_event(base_sha: str) -> dict[str, Any]:
    return {"pull_request": {"number": 7, "base": {"sha": base_sha, "ref": "main"}}}


def _repo_with_semgrep_rules(tmp_path: Path, *, base_sgconfig: bool = True) -> tuple[Path, Path]:
    """A PR checkout carrying scanner rules; ``sgconfig.yml`` is in the base when asked."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    (repo / "app.py").write_text("print('x')\n", encoding="utf-8")
    if base_sgconfig:
        (repo / "sgconfig.yml").write_text("ruleDirs: [rules]\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    rules = repo / ".semgrep.yml"
    rules.write_text("rules: []\n", encoding="utf-8")
    (repo / "sgconfig.yml").write_text("ruleDirs: [rules]\n", encoding="utf-8")
    return repo, rules


def _base_sha(repo: Path) -> str:
    return _git(repo, "rev-parse", "HEAD")


def _pattern_plan(tool_id: str, repo: Path) -> AnalyzerPlan:
    return AnalyzerPlan(
        manifest_id=tool_id, mode="managed", argv=(f"/managed/{tool_id}",), cwd=repo
    )


@pytest.mark.parametrize("tool_id", ["semgrep", "opengrep", "ast-grep"])
def test_untrusted_pattern_scan_uses_shipped_rules(tmp_path: Path, tool_id: str) -> None:
    repo, rules = _repo_with_semgrep_rules(tmp_path)
    plan, ruleset = prepare_pattern_plan(
        _pattern_plan(tool_id, repo),
        manifest=get_manifest(tool_id),
        repo_root=repo,
        file_paths=[str(repo / "app.py")],
        tier="untrusted",
        event=_pr_event(_base_sha(repo)),
    )
    assert plan.mode == "managed", plan.reason
    assert ruleset.source == "default"
    assert str(rules) not in plan.argv
    assert any(str(_CATALOG) in part for part in plan.argv), plan.argv
    assert plan.config_note is not None
    assert "not applied on the untrusted tier" in plan.config_note


@pytest.mark.parametrize("tool_id", ["semgrep", "opengrep"])
def test_untrusted_semgrep_family_scan_applies_no_tree_ignore_files(
    tmp_path: Path, tool_id: str
) -> None:
    repo, _rules = _repo_with_semgrep_rules(tmp_path)
    (repo / ".semgrepignore").write_text("*.py\n", encoding="utf-8")
    kwargs: dict[str, Any] = {
        "manifest": get_manifest(tool_id),
        "repo_root": repo,
        "file_paths": [str(repo / "app.py")],
    }
    untrusted, _ = prepare_pattern_plan(_pattern_plan(tool_id, repo), tier="untrusted", **kwargs)
    trusted, _ = prepare_pattern_plan(_pattern_plan(tool_id, repo), tier="trusted", **kwargs)
    for flag in ("--x-ignore-semgrepignore-files", "--no-git-ignore"):
        assert flag in untrusted.argv, untrusted.argv
        assert flag not in trusted.argv
    # Flags precede the targets, so they are read as options, not file paths.
    assert untrusted.argv[-1] == str(repo / "app.py")


def test_untrusted_astgrep_scan_pins_the_root_config(tmp_path: Path) -> None:
    repo, _rules = _repo_with_semgrep_rules(tmp_path)
    plan, _ = prepare_pattern_plan(
        _pattern_plan("ast-grep", repo),
        manifest=get_manifest("ast-grep"),
        repo_root=repo,
        file_paths=[str(repo / "app.py")],
        tier="untrusted",
        event=_pr_event(_base_sha(repo)),
    )
    index = plan.argv.index("-c")
    pinned = Path(plan.argv[index + 1])
    assert pinned == neutral_config_dir() / "sgconfig.yml"
    assert pinned.read_text(encoding="utf-8") == "ruleDirs: []\n"
    assert repo not in pinned.parents


def test_untrusted_astgrep_needs_the_base_revision_opt_in(tmp_path: Path) -> None:
    """An ``sgconfig.yml`` only in the reviewed tree does not turn ast-grep on."""
    repo, _rules = _repo_with_semgrep_rules(tmp_path, base_sgconfig=False)
    kwargs: dict[str, Any] = {
        "manifest": get_manifest("ast-grep"),
        "repo_root": repo,
        "file_paths": [str(repo / "app.py")],
    }
    untrusted, _ = prepare_pattern_plan(
        _pattern_plan("ast-grep", repo),
        tier="untrusted",
        event=_pr_event(_base_sha(repo)),
        **kwargs,
    )
    assert untrusted.mode == "skip"
    assert untrusted.argv == ()
    assert untrusted.reason is not None
    assert "base revision" in untrusted.reason

    no_event, _ = prepare_pattern_plan(
        _pattern_plan("ast-grep", repo), tier="untrusted", event={}, **kwargs
    )
    assert no_event.mode == "skip"

    trusted, _ = prepare_pattern_plan(_pattern_plan("ast-grep", repo), tier="trusted", **kwargs)
    assert trusted.mode == "managed"
    assert "-c" not in trusted.argv


def test_trusted_pattern_scan_keeps_repo_rules(tmp_path: Path) -> None:
    repo, rules = _repo_with_semgrep_rules(tmp_path)
    plan, ruleset = prepare_pattern_plan(
        _pattern_plan("semgrep", repo),
        manifest=get_manifest("semgrep"),
        repo_root=repo,
        file_paths=[str(repo / "app.py")],
        tier="trusted",
    )
    assert ruleset.source == "repo"
    assert str(rules) in plan.argv


_EXPECTED_ARGV_OVERRIDES: dict[str, tuple[str, ...]] = {
    "actionlint": ("-config-file",),
    "hadolint": ("--config",),
    "shellcheck": ("--norc",),
    "zizmor": ("--no-config",),
    "yamllint": ("-d", "default"),
    "squawk": ("--config",),
    "osv-scanner": ("--config",),
    "trivy": ("--config", "--ignorefile"),
    "buf": ("--config", "--against-config"),
    "oasdiff": ("--config",),
}


def _finalized(tool_id: str, repo: Path, *, tier: TrustTier, argv: tuple[str, ...]) -> AnalyzerPlan:
    manifest = get_manifest(tool_id)
    plan = AnalyzerPlan(manifest_id=tool_id, mode="managed", argv=argv, cwd=repo)
    return finalize_plan(
        plan,
        manifest=manifest,
        repo_root=repo,
        changed_files=["target.txt"],
        tier=tier,
    )


def _manifest_argv(tool_id: str) -> tuple[str, ...]:
    if tool_id == "trivy":
        return ("/managed/trivy", "fs", "--quiet", "--format", "json", "/repo")
    command = list(get_manifest(tool_id).command)
    command[0] = f"/managed/{tool_id}"
    return tuple(part for part in command if part != "{files}")


@pytest.mark.parametrize("tool_id", sorted(_EXPECTED_ARGV_OVERRIDES))
def test_untrusted_scan_pins_neutral_config(tmp_path: Path, tool_id: str) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    untrusted = _finalized(tool_id, repo, tier="untrusted", argv=_manifest_argv(tool_id))
    trusted = _finalized(tool_id, repo, tier="trusted", argv=_manifest_argv(tool_id))

    for flag in _EXPECTED_ARGV_OVERRIDES[tool_id]:
        assert flag in untrusted.argv, untrusted.argv
        assert flag not in trusted.argv
    neutral = neutral_config_dir()
    for part in untrusted.argv:
        if part.startswith(str(neutral)):
            assert Path(part).exists()
    assert repo not in neutral.parents


def test_untrusted_tflint_takes_no_repo_config_or_plugins(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    finalized = _finalized(
        "tflint", repo, tier="untrusted", argv=("/managed/tflint", "--format", "sarif")
    )
    neutral = neutral_config_dir()
    assert finalized.env["TFLINT_CONFIG_FILE"] == str(neutral / "empty.hcl")
    plugin_dir = Path(finalized.env["TFLINT_PLUGIN_DIR"])
    assert plugin_dir.is_dir()
    assert list(plugin_dir.iterdir()) == []


def test_untrusted_buf_lint_pins_the_module_config(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    argv = ("/managed/buf", "lint", str(repo / "a.proto"), "--error-format", "json")
    untrusted = _finalized("buf", repo, tier="untrusted", argv=argv)
    trusted = _finalized("buf", repo, tier="trusted", argv=argv)
    neutral = neutral_config_dir()
    assert untrusted.argv[:4] == ("/managed/buf", "lint", "--config", str(neutral / "buf.yaml"))
    assert "--against-config" not in untrusted.argv
    assert "--config" not in trusted.argv


def test_untrusted_checkov_runs_from_an_empty_directory_outside_the_tree(tmp_path: Path) -> None:
    """checkov merges a ``.checkov.yaml`` from its cwd; untrusted scans run elsewhere."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".checkov.yaml").write_text("soft-fail: true\n", encoding="utf-8")
    argv = ("/managed/checkov", "-f", str(repo / "main.tf"), "-o", "sarif")
    untrusted = _finalized("checkov", repo, tier="untrusted", argv=argv)
    trusted = _finalized("checkov", repo, tier="trusted", argv=argv)
    assert untrusted.cwd is not None
    assert untrusted.cwd.is_dir()
    assert list(untrusted.cwd.iterdir()) == []
    assert untrusted.cwd != repo
    assert repo not in untrusted.cwd.parents
    assert trusted.cwd == repo
    # Only checkov moves; other scanners keep the checkout as their cwd.
    assert _finalized("shellcheck", repo, tier="untrusted", argv=("/m/shellcheck",)).cwd == repo


def test_neutral_working_directory_is_emptied_for_each_scan(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    argv = ("/managed/checkov", "-f", str(repo / "main.tf"))
    first = _finalized("checkov", repo, tier="untrusted", argv=argv)
    assert first.cwd is not None
    (first.cwd / ".checkov.yaml").write_text("soft-fail: true\n", encoding="utf-8")
    second = _finalized("checkov", repo, tier="untrusted", argv=argv)
    assert second.cwd is not None
    assert list(second.cwd.iterdir()) == []


@pytest.mark.parametrize("tool_id", ["buf", "oasdiff"])
def test_untrusted_differential_scan_ignores_companion_base_files(
    tmp_path: Path, tool_id: str
) -> None:
    """Without a base revision, ``*.base.*`` files in the reviewed tree are not the base."""
    repo = tmp_path / "repo"
    repo.mkdir()
    head = "proto/svc.proto" if tool_id == "buf" else "openapi.yaml"
    companion = "proto/svc.base.proto" if tool_id == "buf" else "openapi.base.yaml"
    for rel in (head, companion):
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text("x\n", encoding="utf-8")
    result = run_differential_adapter(
        tool_id=tool_id,
        repo_root=repo,
        changed_files=[head],
        base_ref="fixture-base",
        tier="untrusted",
    )
    assert result.skipped
    assert result.skip_reason is not None
    assert "not used on the untrusted tier" in result.skip_reason


def _cached_managed_binary(tool_id: str) -> Path | None:
    """The pinned binary when it is already in the managed cache (nothing is downloaded)."""
    manifest = get_manifest(tool_id)
    entry = manifest.provenance.get(provision_platform_key())
    if entry is None:
        return None
    binary = _OPERATOR_CACHE / tool_id / provision_platform_key() / entry.sha256 / tool_id
    return binary if binary.is_file() else None


def _run_finalized(plan: AnalyzerPlan) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(plan.argv),
        cwd=plan.cwd,
        env={**os.environ, **plan.env},
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )


@pytest.mark.integration
def test_real_buf_ignores_head_tree_module_config(tmp_path: Path) -> None:
    binary = _cached_managed_binary("buf")
    if binary is None:
        pytest.skip("pinned buf not in the managed cache")
    repo = tmp_path / "repo"
    (repo / "proto").mkdir(parents=True)
    base_dir = tmp_path / "base" / "proto"
    base_dir.mkdir(parents=True)
    (base_dir / "svc.proto").write_text(
        'syntax = "proto3";\npackage demo.v1;\nmessage Req { string name = 1; int32 age = 2; }\n',
        encoding="utf-8",
    )
    head = repo / "proto" / "svc.proto"
    head.write_text(
        'syntax = "proto3";\npackage demo.v1;\nmessage Req { string name = 1; }\n',
        encoding="utf-8",
    )
    # buf reads the module config beside an absolute-path input.
    (repo / "proto" / "buf.yaml").write_text(
        "version: v1\nbreaking:\n  except: [FIELD_NO_DELETE]\n", encoding="utf-8"
    )
    argv = (
        str(binary),
        "breaking",
        str(head),
        "--against",
        str(base_dir / "svc.proto"),
        "--error-format",
        "json",
    )
    untrusted = _run_finalized(_finalized("buf", repo, tier="untrusted", argv=argv))
    trusted = _run_finalized(_finalized("buf", repo, tier="trusted", argv=argv))
    assert "FIELD_NO_DELETE" in untrusted.stdout, untrusted.stderr
    assert "FIELD_NO_DELETE" not in trusted.stdout


@pytest.mark.integration
def test_real_oasdiff_ignores_head_tree_config(tmp_path: Path) -> None:
    binary = _cached_managed_binary("oasdiff")
    if binary is None:
        pytest.skip("pinned oasdiff not in the managed cache")
    repo = tmp_path / "repo"
    repo.mkdir()
    spec = 'openapi: 3.0.0\ninfo: {title: t, version: "1"}\npaths:\n'
    route = "  {}:\n    get:\n      responses:\n        '200': {{description: ok}}\n"
    base = tmp_path / "base.yaml"
    base.write_text(spec + route.format("/pets") + route.format("/users"), encoding="utf-8")
    head = repo / "openapi.yaml"
    head.write_text(spec + route.format("/pets"), encoding="utf-8")
    (repo / ".oasdiff.yaml").write_text('match-path: "^/pets"\n', encoding="utf-8")
    argv = (str(binary), "breaking", "--format", "json", str(base), str(head))
    untrusted = _run_finalized(_finalized("oasdiff", repo, tier="untrusted", argv=argv))
    trusted = _run_finalized(_finalized("oasdiff", repo, tier="trusted", argv=argv))
    assert "/users" in untrusted.stdout, untrusted.stderr
    assert "/users" not in trusted.stdout


@pytest.mark.integration
def test_real_astgrep_ignores_head_tree_root_config(tmp_path: Path) -> None:
    binary = _cached_managed_binary("ast-grep")
    if binary is None:
        pytest.skip("pinned ast-grep not in the managed cache")
    repo, _rules = _repo_with_semgrep_rules(tmp_path)
    (repo / "app.py").write_text("import os\nos.system(cmd)\n", encoding="utf-8")
    rule = tmp_path / "rule.yml"
    rule.write_text(
        "id: os-system\nlanguage: python\nseverity: error\nmessage: m\n"
        "rule:\n  pattern: os.system($X)\n",
        encoding="utf-8",
    )
    # The reviewed tree maps Python files to another language.
    (repo / "sgconfig.yml").write_text(
        "ruleDirs: []\nlanguageGlobs:\n  html: ['*.py']\n", encoding="utf-8"
    )
    plan, _ = prepare_pattern_plan(
        AnalyzerPlan(manifest_id="ast-grep", mode="managed", argv=(str(binary),), cwd=repo),
        manifest=get_manifest("ast-grep"),
        repo_root=repo,
        file_paths=[str(repo / "app.py")],
        tier="untrusted",
        event=_pr_event(_base_sha(repo)),
    )
    argv = list(plan.argv)
    rule_index = argv.index("-r")
    argv[rule_index + 1] = str(rule)
    untrusted = subprocess.run(
        argv, cwd=repo, capture_output=True, text=True, check=False, timeout=120
    )
    trusted_argv = [arg for arg in argv if arg != "-c" and not arg.endswith("sgconfig.yml")]
    trusted = subprocess.run(
        trusted_argv, cwd=repo, capture_output=True, text=True, check=False, timeout=120
    )
    assert '"ruleId":"os-system"' in untrusted.stdout.replace(" ", ""), untrusted.stderr
    assert '"ruleId":"os-system"' not in trusted.stdout.replace(" ", "")


_CONFIG_DIFF = """\
diff --git a/.semgrepignore b/.semgrepignore
new file mode 100644
--- /dev/null
+++ b/.semgrepignore
@@ -0,0 +1 @@
+src/
diff --git a/infra/.tflint.d/plugins/x b/infra/.tflint.d/plugins/x
new file mode 100644
--- /dev/null
+++ b/infra/.tflint.d/plugins/x
@@ -0,0 +1 @@
+x
diff --git a/app.py b/app.py
--- a/app.py
+++ b/app.py
@@ -1 +1,2 @@
 print('x')
+print('y')
"""


def test_scanner_config_changes_become_findings() -> None:
    findings = scanner_config_change_findings(
        changed_files=[".semgrepignore", "infra/.tflint.d/plugins/x", "app.py", "buf.yaml"],
        diff_text=_CONFIG_DIFF,
    )
    by_path = {finding.path: finding for finding in findings}
    assert set(by_path) == {".semgrepignore", "infra/.tflint.d/plugins/x", "buf.yaml"}
    semgrepignore = by_path[".semgrepignore"]
    assert semgrepignore.rule_id == SCANNER_CONFIG_RULE_ID
    assert semgrepignore.start_line == 1
    assert "semgrep" in semgrepignore.message
    assert "tflint" in by_path["infra/.tflint.d/plugins/x"].message
    # Not in the diff text: reported at file level.
    assert by_path["buf.yaml"].start_line is None


def _pipeline_state(repo: Path, monkeypatch: pytest.MonkeyPatch, *, tier: TrustTier) -> Any:
    # checkov is declared unavailable, so the run reaches the findings stage without
    # spawning anything.
    monkeypatch.setattr(pipeline, "detect_enabled", lambda **_: [get_manifest("checkov")])
    return pipeline.run_analyzer_pipeline(
        repo_root=repo,
        changed_files=[".semgrepignore", "app.py"],
        tier=tier,
        diff_text=_CONFIG_DIFF,
        event_name="pull_request",
        event={},
    )


def test_untrusted_run_reports_a_scanner_config_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".semgrepignore").write_text("src/\n", encoding="utf-8")
    (repo / "app.py").write_text("print('x')\nprint('y')\n", encoding="utf-8")

    untrusted = _pipeline_state(repo, monkeypatch, tier="untrusted")
    trusted = _pipeline_state(repo, monkeypatch, tier="trusted")

    reported = [f for f in untrusted.findings if f.get("rule_id") == SCANNER_CONFIG_RULE_ID]
    assert sorted(f.get("path") for f in reported) == [
        ".semgrepignore",
        "infra/.tflint.d/plugins/x",
    ], untrusted.findings
    assert not [f for f in trusted.findings if f.get("rule_id") == SCANNER_CONFIG_RULE_ID]


def test_pr_head_config_does_not_change_the_untrusted_argv(tmp_path: Path) -> None:
    """Adding scanner config to the tree leaves the untrusted invocation unchanged."""
    repo = tmp_path / "repo"
    repo.mkdir()
    before = _finalized("shellcheck", repo, tier="untrusted", argv=_manifest_argv("shellcheck"))
    (repo / ".shellcheckrc").write_text("disable=all\n", encoding="utf-8")
    (repo / ".semgrep.yml").write_text("rules: []\n", encoding="utf-8")
    after = _finalized("shellcheck", repo, tier="untrusted", argv=_manifest_argv("shellcheck"))
    assert before.argv == after.argv


def _planted(repo: Path, name: str, script: str) -> Path:
    bin_dir = repo / ".venv" / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    path = bin_dir / name
    path.write_text(script, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def test_trusted_version_probe_gets_the_scrubbed_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "probe-canary-value")
    repo = tmp_path / "repo"
    repo.mkdir()
    _planted(repo, "shellcheck", '#!/bin/sh\necho "1.0.0 key=${ANTHROPIC_API_KEY:-none}"\n')

    resolution = find_repo_binary(repo, "shellcheck")

    assert resolution is not None
    assert resolution.version == "1.0.0 key=none"


def test_untrusted_resolution_never_probes_the_tree(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    marker = tmp_path / "probed"
    _planted(repo, "shellcheck", f"#!/bin/sh\ntouch '{marker}'\necho 1.0.0\n")

    plan = resolve_analyzer(
        manifest=get_manifest("shellcheck"),
        repo_root=repo,
        managed_available=True,
        tier="untrusted",
    )

    assert plan.mode == "managed"
    assert not marker.exists()
