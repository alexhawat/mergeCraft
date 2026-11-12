"""``trust show`` previews the sandbox tier for a same-repo PR, labelled as such (#1344)."""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.trust_credentials.support import write_trust_config
from typer.testing import CliRunner

from mergecraft.cli.app import app

_ENV = {"NO_COLOR": "1", "TERM": "dumb", "COLUMNS": "200"}


@pytest.mark.parametrize(
    "tier", ["never", "dispatch", "same-repo"], ids=["never", "dispatch", "same-repo"]
)
def test_show_never_claims_the_local_run_is_a_fork(tier: str, tmp_path: Path) -> None:
    """The preview is a same-repo scenario, so the fork floor is never the answer."""
    write_trust_config(tmp_path, agent_sandbox=tier, self_review="analyzers")

    result = CliRunner().invoke(app, ["trust", "show", "--cwd", str(tmp_path)], env=_ENV)

    assert result.exit_code == 0, result.output
    out = " ".join(result.output.split())
    assert "fork head is a hard floor" not in out
    assert "simulated same-repo pull_request_target" in out


def test_show_answers_differ_between_never_and_same_repo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With the operator override requested, the answer depends on the configured tier."""
    monkeypatch.setenv("MERGECRAFT_CODEX_SANDBOX", "danger-full-access")
    answers = []
    for tier in ("never", "same-repo"):
        root = tmp_path / tier
        root.mkdir()
        write_trust_config(root, agent_sandbox=tier, self_review="analyzers")
        result = CliRunner().invoke(app, ["trust", "show", "--cwd", str(root)], env=_ENV)
        assert result.exit_code == 0, result.output
        line = next(row for row in result.output.splitlines() if "simulated" in row)
        answers.append(line)

    assert answers[0] != answers[1]
