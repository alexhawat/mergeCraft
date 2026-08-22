"""FE #393 - opt-in anti-slop analyzer (W9 RED -> W10-W12 green)."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from mergecraft.analyzers.registry import detect_enabled, get_manifest
from mergecraft.analyzers.trust import IN_PROCESS_ANALYZER_IDS
from mergecraft.review_taxonomy import FINDING_CATEGORIES
from tests.analyzers.support import import_module

_FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "antislop"
_POSITIVE = _FIXTURE_ROOT / "positive"
_FALSE_POSITIVE = _FIXTURE_ROOT / "false-positive"

V1_RULE_IDS = (
    "antislop/placeholder-implementation",
    "antislop/placeholder-comment",
    "antislop/narrator-comment",
    "antislop/step-comment",
    "antislop/section-divider-spam",
    "antislop/empty-error-handler",
    "antislop/error-obscuring-catch",
    "antislop/pass-through-wrapper",
    "antislop/wrong-language-idiom",
    "antislop/phantom-import",
    "antislop/lint-evasion",
    "antislop/type-evasion",
)

_FORBIDDEN_MESSAGE_TOKENS = (
    "ai-generated",
    "ai generated",
    "slop score",
    "probability",
)


def _rule_stem(rule_id: str) -> str:
    return rule_id.rsplit("/", 1)[-1]


def _fixture_paths(kind: str, rule_id: str) -> list[Path]:
    stem = _rule_stem(rule_id)
    root = _POSITIVE if kind == "positive" else _FALSE_POSITIVE
    return sorted(root.glob(f"{stem}.*"))


def _copy_fixture_repo(tmp_path: Path, relative_paths: list[str]) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".mergecraft").mkdir()
    for rel in relative_paths:
        src = _POSITIVE / rel
        if not src.is_file():
            src = _FALSE_POSITIVE / rel
        dest = repo / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dest)
    return repo


def _adapters():
    return import_module("mergecraft.analyzers.adapters")


def _antislop():
    return import_module("mergecraft.analyzers.antislop")


def test_rules_load_from_yaml_not_code() -> None:
    antislop = _antislop()
    rules = antislop.load_native_rules()
    assert len(rules) == len(V1_RULE_IDS)
    for rule in rules:
        assert rule.rule_id
        assert rule.source_path.endswith((".yaml", ".yml"))


def test_catalog_manifest_contract() -> None:
    manifest = get_manifest("antislop")
    assert manifest.default_enabled is False
    assert manifest.scope == "diff"
    assert manifest.parser == "antislop_native"
    assert manifest.supports_fix is False


def test_default_catalog_skips_without_override(tmp_path: Path) -> None:
    repo = _copy_fixture_repo(tmp_path, ["step-comment.py"])
    enabled = detect_enabled(
        repo_root=repo,
        changed_files=["step-comment.py"],
        settings_overrides={"analyzers": {"overrides": {}}},
    )
    assert all(item.id != "antislop" for item in enabled)


def test_opt_in_override_enables_antislop(tmp_path: Path) -> None:
    repo = _copy_fixture_repo(tmp_path, ["step-comment.py"])
    (repo / ".mergecraft" / "config.yaml").write_text(
        "analyzers:\n  overrides:\n    antislop:\n      enabled: true\n",
        encoding="utf-8",
    )
    enabled = detect_enabled(
        repo_root=repo,
        changed_files=["step-comment.py"],
        settings_overrides={
            "analyzers": {"overrides": {"antislop": {"enabled": True}}},
        },
    )
    assert any(item.id == "antislop" for item in enabled)


def test_finding_shape_and_introduced_by_pr(tmp_path: Path) -> None:
    antislop = _antislop()
    rel = "step-comment.py"
    repo = tmp_path / "repo"
    repo.mkdir()
    target = repo / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(_POSITIVE / rel, target)

    result = antislop.scan_changed_files(repo_root=repo, changed_files=[rel])
    assert result.findings
    finding = result.findings[0]
    assert finding.tool == "antislop"
    assert finding.rule_id.startswith("antislop/")
    assert finding.category in FINDING_CATEGORIES
    assert finding.evidence
    assert finding.introduced_by_pr == "true"
    lowered = f"{finding.message} {finding.rule_id}".lower()
    for token in _FORBIDDEN_MESSAGE_TOKENS:
        assert token not in lowered


@pytest.mark.parametrize("rule_id", V1_RULE_IDS)
def test_every_v1_rule_has_positive_fixture(rule_id: str) -> None:
    assert _fixture_paths("positive", rule_id), f"missing positive fixture for {rule_id}"


@pytest.mark.parametrize("rule_id", V1_RULE_IDS)
def test_every_v1_rule_has_false_positive_fixture(rule_id: str) -> None:
    assert _fixture_paths("false-positive", rule_id), (
        f"missing false-positive fixture for {rule_id}"
    )


@pytest.mark.parametrize("rule_id", V1_RULE_IDS)
def test_positive_fixture_fires_rule(tmp_path: Path, rule_id: str) -> None:
    antislop = _antislop()
    fixtures = list(_fixture_paths("positive", rule_id))
    if not fixtures:
        pytest.fail(f"{rule_id} has no positive fixtures")
    for fixture in fixtures:
        rel = f"src/{fixture.name}"
        repo = tmp_path / f"pos-{fixture.name}"
        repo.mkdir()
        target = repo / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(fixture, target)
        result = antislop.scan_changed_files(repo_root=repo, changed_files=[rel])
        assert not result.skipped, result.skip_reason
        matched = [finding for finding in result.findings if finding.rule_id == rule_id]
        if matched:
            return
    names = ", ".join(fixture.name for fixture in fixtures)
    pytest.fail(f"{rule_id} must fire on at least one of: {names}")


@pytest.mark.parametrize("rule_id", V1_RULE_IDS)
def test_false_positive_fixture_is_clean(tmp_path: Path, rule_id: str) -> None:
    antislop = _antislop()
    for fixture in _fixture_paths("false-positive", rule_id):
        rel = f"src/{fixture.name}"
        repo = tmp_path / f"fp-{fixture.name}"
        repo.mkdir()
        target = repo / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(fixture, target)
        result = antislop.scan_changed_files(repo_root=repo, changed_files=[rel])
        matched = [finding for finding in result.findings if finding.rule_id == rule_id]
        assert not matched, f"{rule_id} must not fire on {fixture.name}"


def test_per_rule_off_honoured(tmp_path: Path) -> None:
    antislop = _antislop()
    repo = _copy_fixture_repo(tmp_path, ["step-comment.py"])
    rel = "step-comment.py"
    shutil.copyfile(_POSITIVE / rel, repo / rel)
    (repo / ".mergecraft" / "config.yaml").write_text(
        "analyzers:\n  overrides:\n    antislop:\n      enabled: true\n"
        "      rules:\n        antislop/step-comment: off\n",
        encoding="utf-8",
    )
    result = antislop.scan_changed_files(repo_root=repo, changed_files=[rel])
    assert not any(finding.rule_id == "antislop/step-comment" for finding in result.findings)


def test_path_ignore_honoured(tmp_path: Path) -> None:
    antislop = _antislop()
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".mergecraft").mkdir()
    (repo / "generated").mkdir()
    rel = "generated/step-comment.py"
    shutil.copyfile(_POSITIVE / "step-comment.py", repo / rel)
    (repo / ".mergecraft" / "config.yaml").write_text(
        "analyzers:\n  overrides:\n    antislop:\n      enabled: true\n"
        "      ignore:\n        - generated/**\n",
        encoding="utf-8",
    )
    result = antislop.scan_changed_files(repo_root=repo, changed_files=[rel])
    assert result.skipped, result.skip_reason
    assert result.findings == []


def test_in_process_allowlist_includes_antislop() -> None:
    assert "antislop" in IN_PROCESS_ANALYZER_IDS


def test_adapter_runs_in_process(tmp_path: Path) -> None:
    repo = _copy_fixture_repo(tmp_path, ["lint-evasion.py"])
    rel = "lint-evasion.py"
    shutil.copyfile(_POSITIVE / rel, repo / rel)
    result = _adapters().run_adapter(
        tool_id="antislop",
        repo_root=repo,
        changed_files=[rel],
        tier="trusted",
    )
    assert not result.skipped, result.skip_reason
    assert any(finding.rule_id == "antislop/lint-evasion" for finding in result.findings)
