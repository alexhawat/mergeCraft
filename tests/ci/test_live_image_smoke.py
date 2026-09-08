"""The image live gate must require real terminal-review acceptance."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

from mergecraft.review.offline_result import OfflineReviewResult
from mergecraft.run_outcome import RunOutcome
from scripts import live_image_smoke


@pytest.fixture(autouse=True)
def restore_smoke_budget_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "MERGECRAFT_RUN_TIMEOUT_S",
        "MERGECRAFT_TOKEN_BUDGET",
        "MERGECRAFT_TOOL_CALL_BUDGET",
        "MERGECRAFT_COST_BUDGET_USD",
    ):
        monkeypatch.setenv(key, "1")


@pytest.mark.parametrize(
    "result",
    [
        OfflineReviewResult(success=False, outcome=RunOutcome.configuration_error),
        OfflineReviewResult(success=True, outcome=RunOutcome.passed),
        OfflineReviewResult(success=True, structured_output="{}"),
    ],
)
async def test_live_smoke_rejects_nonterminal_results(
    monkeypatch: pytest.MonkeyPatch, result: OfflineReviewResult
) -> None:
    monkeypatch.setenv("MERGECRAFT_E2E_LIVE_MODEL", "openai/test")

    async def review(**kwargs: Any) -> OfflineReviewResult:
        assert kwargs["use_cache"] is False
        assert kwargs["diff_file"].is_file()
        assert os.environ["MERGECRAFT_RUN_TIMEOUT_S"] == "180"
        return result

    monkeypatch.setattr(live_image_smoke, "run_offline_diff_review", review)
    with pytest.raises(RuntimeError, match="accepted terminal"):
        await live_image_smoke.main()


async def test_live_smoke_reports_accepted_terminal(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("MERGECRAFT_E2E_LIVE_MODEL", "openai/test")

    async def review(**kwargs: Any) -> OfflineReviewResult:
        return OfflineReviewResult(success=True, outcome=RunOutcome.passed, structured_output="{}")

    monkeypatch.setattr(live_image_smoke, "run_offline_diff_review", review)
    await live_image_smoke.main()
    assert '"terminal_review": true' in capsys.readouterr().out


@pytest.fixture
def live_step_script() -> str:
    workflow = yaml.safe_load(
        (Path(__file__).resolve().parents[2] / ".github/workflows/e2e.yml").read_text()
    )
    return next(
        step["run"]
        for job in workflow["jobs"].values()
        for step in job.get("steps", [])
        if step.get("name") == "Live installed-harness smoke (explicit model required)"
    )


@pytest.mark.parametrize(
    ("model", "expected_key"),
    [
        ("openai/test", "OPENAI_API_KEY"),
        ("anthropic/test", "ANTHROPIC_API_KEY"),
        ("google/test", "GEMINI_API_KEY"),
        ("unknown/test", None),
        ("openai/test-missing", None),
    ],
)
def test_live_container_gets_only_its_selected_credential(
    tmp_path: Path, live_step_script: str, model: str, expected_key: str | None
) -> None:
    docker = tmp_path / "docker"
    arguments = tmp_path / "arguments"
    docker.write_text('#!/bin/bash\nprintf "%s\\n" "$@" > "$SMOKE_DOCKER_ARGS"\n')
    docker.chmod(0o700)
    keys = {"OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY"}
    environment = {
        **os.environ,
        **dict.fromkeys(keys, "nonsecret-fixture"),
        "PATH": f"{tmp_path}:{os.environ['PATH']}",
        "SMOKE_DOCKER_ARGS": str(arguments),
        "E2E_IMAGE": "test-image",
        "MERGECRAFT_E2E_LIVE_MODEL": model,
    }
    if model.endswith("-missing"):
        environment["OPENAI_API_KEY"] = ""
    result = subprocess.run(
        ["bash", "-c", live_step_script], env=environment, capture_output=True, text=True
    )
    if expected_key is None:
        assert result.returncode != 0
        assert not arguments.exists()
    else:
        assert result.returncode == 0, result.stderr
        passed = set(arguments.read_text().splitlines())
        assert passed.intersection(keys) == {expected_key}
        assert "nonsecret-fixture" not in passed
