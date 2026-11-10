"""Untrusted-tier scanners take rules and config from mergeCraft, not the reviewed tree.

Also covers the trusted-tier version probe: it runs through the analyzer spawn
path with the scrubbed environment.
"""

from __future__ import annotations

import stat
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from mergecraft.analyzers.detect import find_repo_binary
from mergecraft.analyzers.execution import finalize_plan, neutral_config_dir
from mergecraft.analyzers.pattern import prepare_pattern_plan
from mergecraft.analyzers.registry import get_manifest
from mergecraft.analyzers.resolve import AnalyzerPlan, resolve_analyzer

if TYPE_CHECKING:
    from mergecraft.analyzers.manifest import TrustTier

_CATALOG = Path(__file__).resolve().parents[2] / "src" / "mergecraft" / "analyzers" / "catalog"


def _repo_with_semgrep_rules(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    repo.mkdir()
    rules = repo / ".semgrep.yml"
    rules.write_text("rules: []\n", encoding="utf-8")
    (repo / "sgconfig.yml").write_text("ruleDirs: [rules]\n", encoding="utf-8")
    (repo / "app.py").write_text("print('x')\n", encoding="utf-8")
    return repo, rules


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
    )
    assert ruleset.source == "default"
    assert str(rules) not in plan.argv
    assert any(str(_CATALOG) in part for part in plan.argv), plan.argv
    assert plan.config_note is not None
    assert "not applied on the untrusted tier" in plan.config_note


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
