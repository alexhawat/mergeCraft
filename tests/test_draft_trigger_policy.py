"""Action review policy is enforced before setup or provider dispatch."""

from __future__ import annotations

import base64
from typing import TYPE_CHECKING, Any

import pytest

from mergecraft.config import RepoSettings
from tests.support.run_main_harness import FakeGitHubClient, run_main_for_test

if TYPE_CHECKING:
    from pathlib import Path


def _event(*, action: str, draft: bool) -> dict[str, Any]:
    repo = {"full_name": "acme/demo", "fork": False}
    return {
        "action": action,
        "number": 7,
        "pull_request": {
            "number": 7,
            "draft": draft,
            "head": {"sha": "1" * 40, "ref": "feature", "repo": repo},
            "base": {"sha": "2" * 40, "ref": "main", "repo": repo},
            "author_association": "MEMBER",
        },
        "repository": repo,
        "sender": {"login": "contributor"},
    }


@pytest.mark.parametrize("action", ["opened", "synchronize"], ids=["opened", "push"])
async def test_drafts_default_to_neutral_action_noop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, action: str
) -> None:
    record = await run_main_for_test(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        event_name="pull_request",
        event_payload=_event(action=action, draft=True),
        capture_status_checks=True,
    )
    assert record.result is not None
    assert record.result.success
    assert not record.agent_runs
    assert "setup_git" not in record.events
    assert "setup_script" not in record.events
    assert "start_mcp_http_server" not in record.events
    assert {item["name"]: item["conclusion"] for item in record.status_check_runs} == {
        "mergecraft": "neutral",
        "mergecraft-approval": "neutral",
    }


async def test_ready_for_review_runs_normal_agent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = await run_main_for_test(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        event_name="pull_request",
        event_payload=_event(action="ready_for_review", draft=False),
    )
    assert record.agent_runs


@pytest.mark.parametrize(
    ("event_name", "draft_policy", "runs_agent"),
    [
        pytest.param("pull_request_target", "full", True, id="base-full"),
        pytest.param("pull_request", "full", False, id="head-full-ignored"),
        pytest.param("pull_request_target", "lite", False, id="base-lite-never-full"),
    ],
)
async def test_draft_overrides_only_apply_from_operator_settings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    event_name: str,
    draft_policy: str,
    runs_agent: bool,
) -> None:
    settings = RepoSettings.model_validate({"review": {"drafts": draft_policy}})
    record = await run_main_for_test(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        settings=settings,
        event_name=event_name,
        event_payload=_event(action="opened", draft=True),
    )
    assert bool(record.agent_runs) is runs_agent


@pytest.mark.parametrize(
    ("base_policy", "runs_agent"),
    [
        pytest.param("full", True, id="base-full-over-head-skip"),
        pytest.param("lite", False, id="base-lite-over-head-skip"),
    ],
)
async def test_native_review_reads_policy_at_base_sha(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, base_policy: str, runs_agent: bool
) -> None:
    seen_refs: list[str] = []

    async def get(_self: FakeGitHubClient, path: str, **kwargs: Any) -> dict[str, Any]:
        if path.endswith("/contents/.mergecraft/config.yaml"):
            seen_refs.append(kwargs["params"]["ref"])
            return {
                "type": "file",
                "encoding": "base64",
                "content": base64.b64encode(
                    f"review:\n  drafts: {base_policy}\n".encode()
                ).decode(),
            }
        return {}

    monkeypatch.setattr(FakeGitHubClient, "get", get)
    record = await run_main_for_test(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        settings=RepoSettings.model_validate({"review": {"drafts": "skip"}}),
        event_name="pull_request",
        event_payload=_event(action="opened", draft=True),
    )
    assert bool(record.agent_runs) is runs_agent
    assert seen_refs
    assert set(seen_refs) == {"2" * 40}
    if base_policy == "lite":
        assert record.result is not None
        assert "Draft lite" in (record.result.result or "")


@pytest.mark.parametrize(
    ("frequency", "action", "prior_review", "runs_agent"),
    [
        pytest.param("everyPush", "synchronize", "approved", True, id="every-push"),
        pytest.param("oncePerPr", "synchronize", "approved", False, id="once-already-reviewed"),
        pytest.param("oncePerPr", "synchronize", "none", True, id="once-no-reviewed-history"),
        pytest.param("oncePerPr", "ready_for_review", "approved", True, id="once-ready"),
        pytest.param("oncePerPr", "synchronize", "commented", False, id="once-completed-comment"),
        pytest.param(
            "oncePerPr", "synchronize", "inconclusive", True, id="once-inconclusive-comment"
        ),
        pytest.param(
            "oncePerPr", "synchronize", "request-changes", False, id="once-request-changes-comment"
        ),
        pytest.param("oncePerPr", "synchronize", "spoofed", True, id="once-spoofed-comment"),
        pytest.param("onRequest", "ready_for_review", "none", False, id="request-only"),
    ],
)
async def test_frequency_uses_verified_formal_review_history(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    frequency: str,
    action: str,
    prior_review: str,
    runs_agent: bool,
) -> None:
    from types import SimpleNamespace

    from mergecraft.findings.ledger import REVIEW_BODY_MARKER, render_deterministic_review_block

    request = prior_review == "request-changes"
    outcome = (
        "failed" if request else ("inconclusive" if prior_review == "inconclusive" else "passed")
    )
    packet = SimpleNamespace(
        decision=SimpleNamespace(verdict="failure" if request else "success", reason="test review"),
        agent_terminal_verdict="request_changes" if request else "approve",
    )
    body = render_deterministic_review_block(
        packet=packet,
        run_outcome=outcome,
        verdict_diagnostic="agent_approved_but_blocked" if request else "approved",
        publication_entrypoint="publish_pull_request_review",
    )

    async def list_reviews(
        _self: FakeGitHubClient, *_args: Any, **_kwargs: Any
    ) -> list[dict[str, Any]]:
        if prior_review == "none":
            return []
        return [
            {
                "state": "APPROVED" if prior_review == "approved" else "COMMENTED",
                "commit_id": "3" * 40,
                "body": f"{body}\n{REVIEW_BODY_MARKER}\n*via mergecraft*",
                "user": {
                    "login": "contributor" if prior_review == "spoofed" else "mergecraft[bot]",
                    "type": "Bot",
                },
            }
        ]

    monkeypatch.setattr(FakeGitHubClient, "list_reviews", list_reviews, raising=False)

    async def get(_self: FakeGitHubClient, path: str, **_kwargs: Any) -> dict[str, Any]:
        return {"login": "mergecraft[bot]"} if path == "/user" else {}

    monkeypatch.setattr(FakeGitHubClient, "get", get)
    record = await run_main_for_test(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        settings=RepoSettings.model_validate({"review": {"triggers": {"frequency": frequency}}}),
        event_name="pull_request_target",
        event_payload=_event(action=action, draft=False),
    )
    assert bool(record.agent_runs) is runs_agent


@pytest.mark.parametrize(
    ("revision", "lite_status"),
    [
        pytest.param("bound", "reviewed", id="bound-head"),
        pytest.param("head", "reviewed", id="head-moved-before-files"),
        pytest.param("base", "reviewed", id="base-moved-during-files"),
        pytest.param("bound", "failed", id="provider-failed"),
        pytest.param("bound", "downgraded", id="provider-unavailable"),
        pytest.param("bound", "raises", id="provider-exception"),
    ],
)
async def test_draft_lite_uses_base_provider_settings_without_full_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, revision: str, lite_status: str
) -> None:
    from mergecraft import main as main_module
    from mergecraft.agents.lite import LiteOutcome

    base = b"""review:
  drafts: lite
  fastPath:
    lite:
      enabled: true
      provider: base-provider/model
      tokenCap: 8000
"""
    calls: list[dict[str, Any]] = []
    files_reads: list[str] = []

    async def get(_self: FakeGitHubClient, path: str, **_kwargs: Any) -> Any:
        if path.endswith("/contents/.mergecraft/config.yaml"):
            return {
                "type": "file",
                "encoding": "base64",
                "content": base64.b64encode(base).decode(),
            }
        if path.endswith("/files"):
            files_reads.append(path)
            return [{"filename": "a.py", "patch": "@@ -1 +1 @@\n-old\n+new"}]
        return {}

    async def get_pull(_self: FakeGitHubClient, *_args: Any) -> dict[str, Any]:
        return {
            "head": {"sha": ("3" if revision == "head" else "1") * 40},
            "base": {"sha": ("4" if revision == "base" and files_reads else "2") * 40},
        }

    async def lite(**kwargs: Any) -> LiteOutcome:
        calls.append(kwargs)
        if lite_status == "raises":
            raise RuntimeError("provider error")
        return LiteOutcome(status=lite_status, reason="test provider outcome")

    monkeypatch.setattr(FakeGitHubClient, "get", get)
    monkeypatch.setattr(FakeGitHubClient, "get_pull", get_pull, raising=False)
    monkeypatch.setattr(main_module, "run_lite_review", lite)
    record = await run_main_for_test(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        event_name="pull_request",
        event_payload=_event(action="opened", draft=True),
        settings=RepoSettings.model_validate(
            {"review": {"drafts": "full", "fastPath": {"lite": {"provider": "head-provider"}}}}
        ),
        capture_status_checks=True,
    )
    assert record.result is not None
    assert record.result.success
    assert not record.agent_runs
    assert "setup_git" not in record.events
    assert "start_mcp_http_server" not in record.events
    assert len(calls) == (1 if revision == "bound" else 0)
    assert len(files_reads) == (0 if revision == "head" else 1)
    if calls:
        assert calls[0]["settings"].review.fast_path.lite.provider == "base-provider/model"
        assert calls[0]["decision"].token_cap == 8_000
        assert "+new" in calls[0]["diff_text"]
    assert {run["conclusion"] for run in record.status_check_runs} == {"neutral"}


async def test_gha_draft_policy_noop_leaves_the_action_step_green(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mergecraft import main as main_module
    from mergecraft.cli import gha_cmd

    real_main = main_module.main
    output = tmp_path / "output"
    work = tmp_path / "harness"
    work.mkdir()

    async def run_with_boundaries() -> Any:
        with monkeypatch.context() as scoped:
            scoped.setattr(main_module, "main", real_main)
            record = await run_main_for_test(
                tmp_path=work,
                monkeypatch=scoped,
                event_name="pull_request",
                event_payload=_event(action="opened", draft=True),
            )
        assert record.raised is None
        return record.result

    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setattr(main_module, "main", run_with_boundaries)
    await gha_cmd._run_main()

    assert "failover_eligible=false" in output.read_text()
    assert "result=Draft pull request;" in output.read_text()


async def test_unavailable_base_does_not_let_head_disable_ready_reviews(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def get(_self: FakeGitHubClient, path: str, **_kwargs: Any) -> dict[str, Any]:
        if path.endswith("/contents/.mergecraft/config.yaml"):
            return {
                "type": "file",
                "encoding": "base64",
                "content": base64.b64encode(b"review:\n  drafts: invalid\n").decode(),
            }
        return {}

    monkeypatch.setattr(FakeGitHubClient, "get", get)
    record = await run_main_for_test(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        event_name="pull_request",
        event_payload=_event(action="ready_for_review", draft=False),
        settings=RepoSettings.model_validate({"review": {"triggers": {"frequency": "onRequest"}}}),
    )
    assert record.agent_runs


async def test_draft_skip_still_rejects_invalid_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mergecraft.run_outcome import RunOutcome

    record = await run_main_for_test(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        event_name="pull_request",
        event_payload=_event(action="opened", draft=True),
        env={"INPUT_TIMEOUT": "not-a-duration"},
    )
    assert record.result is not None
    assert not record.result.success
    assert record.result.outcome == RunOutcome.configuration_error
    assert not record.agent_runs
    assert "setup_git" not in record.events


async def test_authorized_dispatch_bypasses_automatic_policy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = await run_main_for_test(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        event_name="workflow_dispatch",
        event_payload=_event(action="opened", draft=True),
        settings=RepoSettings.model_validate({"review": {"triggers": {"frequency": "onRequest"}}}),
    )
    assert record.agent_runs


@pytest.mark.parametrize(
    "review",
    [
        pytest.param({"drafts": "sometimes"}, id="invalid-draft-tier"),
        pytest.param({"triggers": {"frequency": "weekly"}}, id="invalid-frequency"),
    ],
)
def test_review_policy_rejects_unknown_values(review: dict[str, Any]) -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        RepoSettings.model_validate({"review": review})
