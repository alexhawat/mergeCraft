"""DG5 policy CLI — ``mergecraft policy lint|test|explain`` (G11).

Wave plan: ``.ignorelocal/waves/05-review-depth-governance-wave-plan.md`` (PR DG5).
Implementation: **DG5.2** — ``src/mergecraft/cli/policy_cmd.py``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from tests.policy.conftest import MALFORMED_RULE_YAML, POLICY_LINT_FIXTURES
from typer.testing import CliRunner

from mergecraft.cli.app import app

if TYPE_CHECKING:
    from pathlib import Path

    from _pytest.monkeypatch import MonkeyPatch

runner = CliRunner()


def _write_policy_tree(tmp_path: Path, rules_yaml: str) -> None:
    from tests.orchestrator.conftest import write_repo_config

    write_repo_config(tmp_path)
    policy_dir = tmp_path / ".mergecraft" / "policy"
    policy_dir.mkdir(parents=True)
    (policy_dir / "rules.yaml").write_text(rules_yaml, encoding="utf-8")


def test_policy_lint_rejects_a_malformed_rule(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """``policy lint`` rejects a rule missing required schema fields."""
    _write_policy_tree(tmp_path, MALFORMED_RULE_YAML)
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["policy", "lint"])

    assert result.exit_code != 0, result.stdout + result.stderr
    output = (result.stdout + result.stderr).lower()
    if result.exception is not None:
        output += str(result.exception).lower()
    assert "id" in output or "owner" in output or "severity" in output or "config" in output


def test_policy_test_runs_should_trigger_and_should_not_fixtures(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """``policy test`` runs should-trigger and should-not fixtures."""
    _write_policy_tree(tmp_path, POLICY_LINT_FIXTURES)
    fixtures = tmp_path / "fixtures"
    fixtures.mkdir()
    (fixtures / "should-trigger.yaml").write_text(
        "path: src/app.py\nviolation: hardcoded token\n",
        encoding="utf-8",
    )
    (fixtures / "should-not.yaml").write_text(
        "path: README.md\nviolation: none\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(
        app,
        ["policy", "test", "--fixtures", str(fixtures)],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    output = (result.stdout + result.stderr).lower()
    assert "should-trigger" in output
    assert "should-not" in output
    assert "pass" in output or "trigger" in output


def test_policy_explain_names_the_source_of_each_effective_rule(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """``policy explain`` attributes each effective rule to its source layer."""
    _write_policy_tree(tmp_path, POLICY_LINT_FIXTURES)
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(
        app,
        [
            "policy",
            "explain",
            "--path",
            "src/app.py",
            "--org",
            "acme-corp",
            "--repo",
            "payments-api",
            "--symbol",
            "process",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    output = (result.stdout + result.stderr).lower()
    assert "should-trigger" in output
    assert "source" in output or "layer" in output or "org" in output or "repo" in output


def test_policy_lint_validates_exceptions_yaml(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """``policy lint`` validates ``exceptions.yaml`` when present."""
    _write_policy_tree(tmp_path, POLICY_LINT_FIXTURES)
    policy_dir = tmp_path / ".mergecraft" / "policy"
    (policy_dir / "exceptions.yaml").write_text(
        """exceptions:
  - id: temp-waiver
    rule_id: no-hardcoded-secrets
    reason: emergency hotfix with tracked follow-up
    approver: security-lead
    scope:
      path: "src/legacy/**"
    expires_at: "2099-12-31T23:59:59Z"
""",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["policy", "lint"])

    assert result.exit_code == 0, result.stdout + result.stderr
    assert "exception" in (result.stdout + result.stderr).lower()
