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
    # The Codex subscription credential wins over OPENAI_API_KEY for `openai/*`;
    # clear any inherited value so the API-key fallback stays deterministic.
    environment.pop("CODEX_AUTH_JSON", None)
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


def test_unconfigured_live_slice_warns_as_unavailable(
    tmp_path: Path, live_step_script: str
) -> None:
    """No model is not a skip: warn, record unavailable, and stay green."""
    summary = tmp_path / "step-summary"
    summary.write_text("", encoding="utf-8")
    environment = {
        **os.environ,
        "MERGECRAFT_E2E_LIVE_MODEL": "",
        "GITHUB_STEP_SUMMARY": str(summary),
    }
    result = subprocess.run(
        ["bash", "-c", live_step_script],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    output = f"{result.stdout}\n{result.stderr}"
    assert result.returncode == 0, output
    assert "::warning" in output, f"an unconfigured live slice must emit a warning:\n{output}"
    assert "unavailable" in summary.read_text(encoding="utf-8").lower(), (
        "the step summary must record the live slice as unavailable"
    )
    assert "skipped" not in output.lower(), (
        f"'skipped' claims a test that never ran; say unavailable instead:\n{output}"
    )


_LIVE_CREDENTIAL_KEYS = (
    "OPENAI_API_KEY",
    "CODEX_AUTH_JSON",
    "ANTHROPIC_API_KEY",
    "GEMINI_API_KEY",
)


def _run_live_step(
    tmp_path: Path,
    script: str,
    *,
    model: str,
    extra_env: dict[str, str],
    docker_body: str = '#!/bin/bash\nprintf "%s\\n" "$@" > "$SMOKE_DOCKER_ARGS"\n',
) -> tuple[subprocess.CompletedProcess[str], Path]:
    """Run the extracted live step with a fake ``docker`` on ``PATH``.

    ``extra_env`` is the only source of live credentials: inherited provider
    keys and the Codex subscription are cleared unless named there, so each
    case exercises exactly the credential it declares.
    """
    docker = tmp_path / "docker"
    arguments = tmp_path / "arguments"
    docker.write_text(docker_body, encoding="utf-8")
    docker.chmod(0o700)
    environment = {
        **os.environ,
        "PATH": f"{tmp_path}:{os.environ['PATH']}",
        "SMOKE_DOCKER_ARGS": str(arguments),
        "E2E_IMAGE": "test-image",
        "MERGECRAFT_E2E_LIVE_MODEL": model,
        **extra_env,
    }
    for key in _LIVE_CREDENTIAL_KEYS:
        if key not in extra_env:
            environment.pop(key, None)
    result = subprocess.run(
        ["bash", "-c", script],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    return result, arguments


def test_codex_subscription_credential_is_selected_for_openai_models(
    tmp_path: Path, live_step_script: str
) -> None:
    """``openai/*`` with only ``CODEX_AUTH_JSON`` passes the subscription credential in."""
    result, arguments = _run_live_step(
        tmp_path,
        live_step_script,
        model="openai/gpt-5.3-codex",
        extra_env={"CODEX_AUTH_JSON": "nonsecret-fixture"},
    )
    assert result.returncode == 0, result.stderr
    passed = set(arguments.read_text(encoding="utf-8").splitlines())
    assert "CODEX_AUTH_JSON" in passed, f"the container must receive the subscription: {passed}"
    assert "OPENAI_API_KEY" not in passed, f"only one credential may pass: {passed}"
    assert "nonsecret-fixture" not in passed, "the secret value must not ride on argv"


def test_openai_model_without_api_key_or_subscription_exits_non_zero(
    tmp_path: Path, live_step_script: str
) -> None:
    """Neither credential set is a configured-but-broken run: fail, do not skip."""
    result, arguments = _run_live_step(
        tmp_path,
        live_step_script,
        model="openai/gpt-5.3-codex",
        extra_env={},
    )
    assert result.returncode != 0, result.stdout + result.stderr
    assert not arguments.exists()


@pytest.mark.parametrize("marker", ["refresh token", "401", "invalid_grant"])
def test_rejected_subscription_credential_reads_as_unavailable(
    tmp_path: Path, live_step_script: str, marker: str
) -> None:
    """A rejected Codex session is named unavailable, not reported as a product failure."""
    docker_body = f'#!/bin/bash\nprintf "codex auth error: {marker}\\n" >&2\nexit 1\n'
    result, _ = _run_live_step(
        tmp_path,
        live_step_script,
        model="openai/gpt-5.3-codex",
        extra_env={"CODEX_AUTH_JSON": "nonsecret-fixture"},
        docker_body=docker_body,
    )
    output = f"{result.stdout}\n{result.stderr}".lower()
    assert result.returncode != 0, output
    assert "unavailable credential" in output, output


def test_product_failure_is_not_reported_as_unavailable_credential(
    tmp_path: Path, live_step_script: str
) -> None:
    """A genuine product failure must keep the unavailable-credential label off."""
    docker_body = (
        "#!/bin/bash\n"
        'printf "review harness rejected the diff: no terminal result\\n" >&2\n'
        "exit 1\n"
    )
    result, _ = _run_live_step(
        tmp_path,
        live_step_script,
        model="openai/gpt-5.3-codex",
        extra_env={"CODEX_AUTH_JSON": "nonsecret-fixture"},
        docker_body=docker_body,
    )
    output = f"{result.stdout}\n{result.stderr}".lower()
    assert result.returncode != 0, output
    assert "unavailable credential" not in output, output


def test_live_slice_job_serializes_the_subscription_credential() -> None:
    """Codex refresh tokens rotate, so the live-slice job must not run concurrently."""
    workflow = yaml.safe_load(
        (Path(__file__).resolve().parents[2] / ".github/workflows/e2e.yml").read_text()
    )
    live_job = next(
        job
        for job in workflow["jobs"].values()
        if any(
            step.get("name") == "Live installed-harness smoke (explicit model required)"
            for step in job.get("steps", [])
        )
    )
    concurrency = live_job.get("concurrency")
    assert isinstance(concurrency, dict), concurrency
    assert concurrency.get("group") == "codex-subscription-auth", concurrency
    assert concurrency.get("cancel-in-progress") is False, concurrency
