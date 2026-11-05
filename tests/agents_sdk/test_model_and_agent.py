"""Model resolution and review_agent tool wiring (no network)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("agents")

from mergecraft.agents_sdk.agent import review_agent
from mergecraft.agents_sdk.model import AgentsSdkModelConfig, resolve_model_config
from mergecraft.agents_sdk.types import ReviewFinding, ReviewFindingsReport


def test_resolve_model_config_openai_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.delenv("OPENCODE_GO_API_KEY", raising=False)
    monkeypatch.delenv("MERGECRAFT_CUSTOM_PROVIDER_API_KEY", raising=False)
    cfg = resolve_model_config()
    assert cfg.api_key == "test-key"
    assert cfg.openai_model_name() == "gpt-4o-mini"


def test_resolve_model_config_opencode_go_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("OPENCODE_GO_API_KEY", "go-key")
    cfg = resolve_model_config()
    assert cfg.api_key == "go-key"
    assert cfg.base_url == "https://opencode.ai/zen/v1"
    assert cfg.model.endswith("deepseek-v4.1-flash")


def test_resolve_model_config_custom_provider_requires_model_slug(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENCODE_GO_API_KEY", raising=False)
    monkeypatch.setenv("MERGECRAFT_CUSTOM_PROVIDER_API_KEY", "custom-key")
    monkeypatch.setenv("MERGECRAFT_CUSTOM_PROVIDER_BASE_URL", "https://example.invalid/v1")
    monkeypatch.delenv("MERGECRAFT_AGENTS_SDK_MODEL", raising=False)
    with pytest.raises(ValueError, match="MERGECRAFT_AGENTS_SDK_MODEL"):
        resolve_model_config()


def test_resolve_model_config_custom_provider_with_slug(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENCODE_GO_API_KEY", raising=False)
    monkeypatch.setenv("MERGECRAFT_CUSTOM_PROVIDER_API_KEY", "custom-key")
    monkeypatch.setenv("MERGECRAFT_CUSTOM_PROVIDER_BASE_URL", "https://example.invalid/v1")
    cfg = resolve_model_config(model="acme/chat-model")
    assert cfg.api_key == "custom-key"
    assert cfg.base_url == "https://example.invalid/v1"
    assert cfg.api_key_env == "MERGECRAFT_CUSTOM_PROVIDER_API_KEY"


def test_review_agent_exposes_mergecraft_tools(tmp_path: Path) -> None:
    config = AgentsSdkModelConfig(
        model="gpt-4o-mini",
        base_url=None,
        api_key_env="OPENAI_API_KEY",
        api_key="dummy",
    )
    agent = review_agent(
        repo_root=tmp_path,
        model_config=config,
        allowed_paths=frozenset({"src/demo.py"}),
    )
    tool_names = {getattr(tool, "name", None) or tool.__name__ for tool in agent.tools}
    assert "get_workspace_change" in tool_names
    assert "review_change" in tool_names
    assert "get_policy" in tool_names


@pytest.mark.asyncio
async def test_get_workspace_change_surfaces_demo_bug() -> None:
    from agents.tool import ToolContext

    root = Path("examples/agents-sdk/workspace")
    config = AgentsSdkModelConfig(
        model="gpt-4o-mini",
        base_url=None,
        api_key_env="OPENAI_API_KEY",
        api_key="dummy",
    )
    agent = review_agent(
        repo_root=root,
        model_config=config,
        allowed_paths=frozenset({"src/demo.py"}),
    )
    tool = next(item for item in agent.tools if item.name == "get_workspace_change")
    ctx = ToolContext(
        context=None,
        tool_call_id="1",
        tool_name="get_workspace_change",
        tool_arguments="{}",
    )
    payload = await tool.on_invoke_tool(ctx, "{}")
    body = payload["files"]["src/demo.py"]
    assert "return a / b" in body
    assert "if b == 0" not in body


@pytest.mark.asyncio
async def test_review_agent_e2e_fake_model_surfaces_demo_bug(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agents import Runner

    root = Path("examples/agents-sdk/workspace")
    config = AgentsSdkModelConfig(
        model="gpt-4o-mini",
        base_url=None,
        api_key_env="OPENAI_API_KEY",
        api_key="dummy",
    )
    agent = review_agent(
        repo_root=root,
        model_config=config,
        allowed_paths=frozenset({"src/demo.py"}),
    )

    async def fake_run(review_agent: object, input: str, **kwargs: object) -> SimpleNamespace:
        from agents.tool import ToolContext

        tool = next(item for item in review_agent.tools if item.name == "get_workspace_change")  # type: ignore[attr-defined]
        ctx = ToolContext(
            context=None,
            tool_call_id="1",
            tool_name="get_workspace_change",
            tool_arguments="{}",
        )
        change = await tool.on_invoke_tool(ctx, "{}")
        body = change["files"]["src/demo.py"]
        findings: list[ReviewFinding] = []
        if "return a / b" in body and "if b == 0" not in body:
            findings.append(
                ReviewFinding(
                    severity="Major",
                    file="src/demo.py",
                    message="divide() does not guard division by zero",
                )
            )
        return SimpleNamespace(final_output=ReviewFindingsReport(findings=findings))

    monkeypatch.setattr(Runner, "run", fake_run)
    result = await Runner.run(agent, input="Review src/demo.py")
    report = result.final_output
    assert isinstance(report, ReviewFindingsReport)
    assert report.blocking_findings()
