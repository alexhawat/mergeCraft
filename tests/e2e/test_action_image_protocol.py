"""Host checks for the same MCP client and assertions used by image E2E."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import threading
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
E2E = ROOT / "docker" / "e2e"


def load_helper(name: str, relative: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, E2E / relative)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.hermetic_integration
async def test_fake_provider_runs_real_scope_read_analysis_and_terminal_protocol(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import httpx

    from mergecraft.mcp.context import PayloadEvent, RepoIdentity, ResolvedPayload, ToolContext
    from mergecraft.mcp.server import start_mcp_http_server
    from mergecraft.mcp.tool_state import init_tool_state, primary_repo_state
    from mergecraft.modes import compute_modes
    from mergecraft.utils import workspace as workspace_utils
    from mergecraft.utils.github import GitHubClient

    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "gitconfig"))
    monkeypatch.setattr(workspace_utils, "_workspace_roots", set())
    monkeypatch.setattr(workspace_utils, "_safe_directories_added", set())
    prepare = load_helper("action_prepare", "prepare_fixture.py")
    mock = load_helper("action_mock", "mock_github_api.py")
    fake = load_helper("action_fake", "fake-provider-cli/fake_provider.py")
    event = await asyncio.to_thread(prepare.prepare, tmp_path, "pull_request", container=False)
    repo = tmp_path / "workspace"
    monkeypatch.chdir(repo)
    monkeypatch.setenv("GITHUB_WORKSPACE", str(repo))
    server = mock.create_server("127.0.0.1", 0, tmp_path / "records")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    api_url = f"http://127.0.0.1:{server.server_port}"
    async with httpx.AsyncClient() as http:
        configured = await http.post(api_url + "/_e2e/fixture", json=event)
        configured.raise_for_status()
    client = GitHubClient("fixture-token", base_url=api_url)
    ctx = ToolContext(
        agent_id="claude",
        repo=RepoIdentity(owner="acme", name="demo"),
        payload=ResolvedPayload(
            event=PayloadEvent(trigger="pull_request_synchronize", issue_number=42, is_pr=True)
        ),
        github=client,
        tool_state=init_tool_state(owner="acme", name="demo", dir=str(repo)),
        modes=compute_modes("claude"),
        tmpdir=str(tmp_path / "runner-temp"),
        gh_event=event,
        trust_tier="trusted",
        authority_trust="trusted",
    )
    url, stop = start_mcp_http_server(ctx, output_schema=fake.OUTPUT_SCHEMA)
    config = tmp_path / "mcp.json"
    await asyncio.to_thread(
        config.write_text,
        json.dumps(
            {
                "mcpServers": {
                    "reviewer": {
                        "url": url + "/reviewer",
                        "headers": {"Authorization": f"Bearer {ctx.mcp_auth_token}"},
                    }
                }
            }
        ),
    )
    try:
        output = await asyncio.to_thread(fake.review, config)
        assert output["head_sha"] == event["pull_request"]["head"]["sha"]
        assert primary_repo_state(ctx.tool_state).checkout_sha == output["head_sha"]
        assert ctx.tool_state.terminal_submission is not None
        assert ctx.tool_state.terminal_submission.id == output["terminal_id"]
        assert ctx.tool_state.terminal_submission.verdict == "approve"
        assert {call.tool for call in ctx.tool_state.tool_calls if call.ok} >= fake.REQUIRED_TOOLS
        assert json.loads(ctx.tool_state.output) == output
    finally:
        await asyncio.to_thread(stop)
        await client.aclose()
        await asyncio.to_thread(server.shutdown)
        server.server_close()
        thread.join(timeout=5)


def _successful_records() -> tuple[dict, list, list]:
    sha = "a" * 40
    output = {"outcome": "passed", "head_sha": sha, "terminal_id": "terminal-1"}
    packet = {
        "reviewed_head_sha": sha,
        "agent_terminal_verdict": "approve",
        "decision": {"verdict": "success"},
        "trajectory": {
            "tool_calls": [
                {"tool": tool, "ok": True}
                for tool in (
                    "select_mode",
                    "checkout_pr",
                    "git",
                    "run_analyzers",
                    "submit_review_verdict",
                )
            ]
        },
    }
    runs = [
        {
            "body": {
                "name": name,
                "head_sha": sha,
                "status": "completed",
                "conclusion": "success",
                "output": {"summary": "Reviewed fixture"},
            }
        }
        for name in ("mergecraft", "mergecraft-approval")
    ]
    publications = [
        {
            "method": "POST",
            "path": "/repos/acme/demo/pulls/42/reviews",
            "body": {"commit_id": sha, "event": "APPROVE"},
        }
    ]
    return (
        {
            "result": json.dumps(output),
            "evidence_packet": json.dumps(packet),
            "verdict_diagnostic": "approved",
        },
        runs,
        publications,
    )


@pytest.mark.parametrize(
    "defect",
    [
        "none",
        "prose",
        "wrong-outcome",
        "wrong-result-sha",
        "missing-terminal",
        "missing-packet",
        "wrong-packet-sha",
        "missing-verdict",
        "neutral-packet",
        "missing-scope",
        "missing-read",
        "missing-analyzers",
        "missing-check",
        "neutral-check",
        "failed-check",
        "wrong-check-sha",
        "missing-publication",
        "wrong-publication-sha",
        "wrong-publication-verdict",
        "diagnostic",
    ],
)
def test_output_assertions_reject_incomplete_or_wrong_revision_reviews(defect: str) -> None:
    helper = load_helper("action_assertions", "assert_e2e_outputs.py")
    outputs, runs, publications = _successful_records()
    result = json.loads(outputs["result"])
    packet = json.loads(outputs["evidence_packet"])
    if defect == "wrong-outcome":
        result["outcome"] = "inconclusive"
    elif defect == "wrong-result-sha":
        result["head_sha"] = "b" * 40
    elif defect == "missing-terminal":
        del result["terminal_id"]
    elif defect == "wrong-packet-sha":
        packet["reviewed_head_sha"] = "b" * 40
    elif defect == "missing-verdict":
        del packet["agent_terminal_verdict"]
    elif defect == "neutral-packet":
        packet["decision"]["verdict"] = "neutral"
    elif defect in {"missing-scope", "missing-read", "missing-analyzers"}:
        missing = {
            "missing-scope": "checkout_pr",
            "missing-read": "git",
            "missing-analyzers": "run_analyzers",
        }[defect]
        packet["trajectory"]["tool_calls"] = [
            call for call in packet["trajectory"]["tool_calls"] if call["tool"] != missing
        ]
    elif defect == "missing-check":
        runs.pop()
    elif defect in {"neutral-check", "failed-check"}:
        runs[0]["body"]["conclusion"] = "neutral" if defect == "neutral-check" else "failure"
    elif defect == "wrong-check-sha":
        runs[1]["body"]["head_sha"] = "b" * 40
    elif defect == "missing-publication":
        publications.clear()
    elif defect == "wrong-publication-sha":
        publications[0]["body"]["commit_id"] = "b" * 40
    elif defect == "wrong-publication-verdict":
        publications[0]["body"]["event"] = "COMMENT"
    elif defect == "diagnostic":
        outputs["verdict_diagnostic"] = "terminal_submission_missing"
    outputs["result"] = "E2E review complete" if defect == "prose" else json.dumps(result)
    outputs["evidence_packet"] = "" if defect == "missing-packet" else json.dumps(packet)
    arguments = {"expected_outcome": "passed", "expected_sha": "a" * 40, "require_checks": True}
    if defect == "none":
        helper.validate_outputs(outputs, runs, publications, **arguments)
    else:
        with pytest.raises(
            ValueError,
            match=r"Expecting value|structured JSON|result must|packet must|MCP review|terminal verdict|completed|must succeed|formal review|error code",
        ):
            helper.validate_outputs(outputs, runs, publications, **arguments)


@pytest.mark.parametrize(
    "raw", ["E2E review complete", '{"outcome":"passed"}', '{"outcome":"configuration_error"}']
)
def test_refused_fixture_requires_structured_error(raw: str) -> None:
    helper = load_helper("action_assertions", "assert_e2e_outputs.py")
    with pytest.raises(ValueError, match=r"Expecting value|structured JSON|error code"):
        helper.validate_outputs(
            {"result": raw},
            [],
            [],
            expected_outcome="configuration_error",
            expected_sha="a" * 40,
            require_checks=False,
        )


@pytest.mark.parametrize("event", ["APPROVE", "REQUEST_CHANGES", "COMMENT"])
def test_refused_fixture_rejects_formal_publication(event: str) -> None:
    helper = load_helper("action_assertions", "assert_e2e_outputs.py")
    with pytest.raises(ValueError, match="must not publish a formal review"):
        helper.validate_outputs(
            {
                "result": json.dumps(
                    {"outcome": "configuration_error", "error": {"code": "refused"}}
                )
            },
            [],
            [
                {
                    "method": "POST",
                    "path": "/repos/acme/demo/pulls/43/reviews",
                    "body": {"event": event},
                }
            ],
            expected_outcome="configuration_error",
            expected_sha="a" * 40,
            require_checks=False,
        )


@pytest.mark.hermetic_integration
@pytest.mark.parametrize("event_name", ["pull_request", "pull_request_target"])
async def test_gha_entrypoint_with_real_mcp_and_local_publication(
    tmp_path: Path,
    event_name: str,
) -> None:
    import os
    import subprocess
    import sys

    import httpx

    prepare = load_helper("action_prepare", "prepare_fixture.py")
    mock = load_helper("action_mock", "mock_github_api.py")
    fake = load_helper("action_fake", "fake-provider-cli/fake_provider.py")
    assertions = load_helper("action_assertions", "assert_e2e_outputs.py")
    event = await asyncio.to_thread(prepare.prepare, tmp_path, event_name, container=False)
    records = tmp_path / "records"
    server = mock.create_server("127.0.0.1", 0, records)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    api_url = f"http://127.0.0.1:{server.server_port}"
    async with httpx.AsyncClient() as http:
        (await http.post(api_url + "/_e2e/fixture", json=event)).raise_for_status()
    home = tmp_path / "home"
    await asyncio.to_thread(home.mkdir)
    env = {
        "PATH": f"{E2E / 'fake-provider-cli'}:{Path(sys.executable).parent}:/usr/bin:/bin",
        "HOME": str(home),
        "PYTHONPATH": str(ROOT / "src"),
        "GITHUB_ACTIONS": "true",
        "CI": "true",
        "GITHUB_WORKSPACE": str(tmp_path / "workspace"),
        "GITHUB_EVENT_PATH": str(tmp_path / "github" / "event.json"),
        "GITHUB_EVENT_NAME": event_name,
        "GITHUB_REPOSITORY": "acme/demo",
        "GITHUB_API_URL": api_url,
        "GITHUB_OUTPUT": str(tmp_path / "github" / "output"),
        "GITHUB_STATE": str(tmp_path / "github" / "state"),
        "RUNNER_TEMP": str(tmp_path / "runner-temp"),
        "MERGECRAFT_TEMP_PARENT": str(tmp_path / "runner-temp"),
        "INPUT_PROMPT": "Review pull request #42",
        "INPUT_TOKEN": "ghs_e2e_fake_token",
        "INPUT_STATUS_CHECKS": "enabled",
        "INPUT_SHELL": "restricted",
        "INPUT_PUSH": "restricted",
        "INPUT_ANALYZERS": "auto",
        "INPUT_OUTPUT_SCHEMA": json.dumps(fake.OUTPUT_SCHEMA),
        "INPUT_MODEL": "anthropic/claude-sonnet",
        "INPUT_MODEL_PIN": "enabled",
        "ANTHROPIC_API_KEY": "sk-e2e-fake-anthropic-key",
        "MERGECRAFT_RUN_TIMEOUT_S": "120",
        "LOGFIRE_SEND_TO_LOGFIRE": "false",
        "LANG": "en_US.UTF-8",
    }
    if "SYSTEMROOT" in os.environ:
        env["SYSTEMROOT"] = os.environ["SYSTEMROOT"]
    try:
        completed = await asyncio.to_thread(
            subprocess.run,
            [sys.executable, "-c", "from mergecraft.cli.app import main; main()", "gha"],
            cwd=tmp_path / "workspace",
            env=env,
            text=True,
            capture_output=True,
            timeout=150,
        )
        await asyncio.to_thread(
            (tmp_path / "gha.log").write_text, completed.stdout + completed.stderr
        )
        assert completed.returncode == (0 if event_name == "pull_request" else 30), (
            completed.stdout[-5000:] + completed.stderr[-5000:]
        )
        assertions.validate_outputs(
            assertions._parse_github_output(tmp_path / "github" / "output"),
            assertions._load_check_runs(records),
            assertions._load_check_runs(records / "requests"),
            expected_outcome="passed" if event_name == "pull_request" else "configuration_error",
            expected_sha=event["pull_request"]["head"]["sha"],
            require_checks=event_name == "pull_request",
        )
    finally:
        await asyncio.to_thread(server.shutdown)
        server.server_close()
        thread.join(timeout=5)
