"""Offline audit evidence for main 55cf88e3; no providers or network calls.

Run from the repository root with PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:.
Only disposable temporary fixtures are mutated. No installed pytest is needed.
Assertions document current bugs, not desired product behavior.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

import httpx
from loguru import logger
from tests.support.tool_context import make_tool_context

import mergecraft.main  # noqa: F401 -- bootstrap product imports
from mergecraft.config.settings import RepoSettings
from mergecraft.config.trust_policy import is_fork_pull_request
from mergecraft.mcp.review_context import hydrate_review_context
from mergecraft.mcp.tool_state import ApprovalRecord, init_tool_state, primary_repo_state
from mergecraft.policy.review import PolicySnapshot, evaluate_review_policy
from mergecraft.policy.schema import PolicyRule
from mergecraft.scm.artifact_provenance import require_workflow_untouched
from mergecraft.utils.diff_paths import changed_paths_from_diff
from mergecraft.utils.github import GitHubClient
from mergecraft.utils.run_bounds import BudgetTracker, resolve_run_bounds
from mergecraft.utils.status_checks import report_status_checks

logger.disable("mergecraft")


def git(root: Path, *args: str) -> str:
    env = {
        **os.environ,
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_SYSTEM": os.devnull,
        "GIT_TERMINAL_PROMPT": "0",
    }
    return subprocess.run(
        [
            "git",
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "user.name=Offline Audit",
            "-c",
            "user.email=offline-audit@example.invalid",
            *args,
        ],
        cwd=root,
        env=env,
        check=True,
        text=True,
        capture_output=True,
    ).stdout


def spaced_diff_probe() -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="mergecraft-audit-paths-") as temp:
        root = Path(temp)
        git(root, "init", "-q")
        original = {
            "scripts/deploy job.sh": b"echo fixture\n",
            "scripts/control.sh": b"echo fixture\n",
            "assets/private key.bin": b"\x00before\n",
            "legacy/old file.py": b"value = 1\n",
            ".github/workflows/deploy proof.yml": b"name: fixture\n",
        }
        for relative, data in original.items():
            file = root / relative
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(data)
        git(root, "add", ".")
        git(root, "commit", "-qm", "offline fixture baseline")
        for relative in (
            "scripts/deploy job.sh",
            "scripts/control.sh",
            ".github/workflows/deploy proof.yml",
        ):
            (root / relative).chmod(0o755)
        (root / "assets/private key.bin").write_bytes(b"\x00after\n")
        (root / "modern").mkdir()
        git(root, "mv", "legacy/old file.py", "modern/new file.py")
        git(root, "add", ".")
        diff = git(root, "diff", "--cached", "--no-ext-diff", "--no-textconv")
        parsed = changed_paths_from_diff(diff)
        assert parsed == ["scripts/control.sh"], parsed
        rule = PolicyRule.model_validate(
            {
                "id": "deploy-proof",
                "owner": "operator",
                "version": 1,
                "rationale": "Changed deployment scripts require proof.",
                "severity": "Major",
                "enforcement": "required",
                "scope": {"path": "scripts/deploy job.sh"},
                "evidence": {"required": ["rollback_plan"]},
            }
        )
        snapshot = PolicySnapshot(repo_root=root, rules=(rule,), operator_owned=True)

        def evaluate(paths: list[str]):
            return evaluate_review_policy(
                snapshot,
                changed_paths=paths,
                org="acme",
                repo="demo",
                base_ref="main",
                exceptions_trusted=True,
                now=datetime(2026, 11, 5, tzinfo=UTC),
            )

        missed = evaluate(parsed)
        expected = evaluate(["scripts/deploy job.sh"])
        assert not missed
        assert [row.severity for row in expected] == ["Major"]
        state = init_tool_state(owner="acme", name="demo", dir=str(root))
        primary_repo_state(state).diff_path = "/synthetic/diff.patch"
        with patch.object(Path, "read_text", return_value=diff):
            require_workflow_untouched(
                state,
                workflow=".github/workflows/deploy proof.yml",
                label="synthetic artifact",
                refuse=RuntimeError,
            )
        return {
            "git_headers": [line for line in diff.splitlines() if line.startswith("diff --git")],
            "parsed_paths": parsed,
            "policy_rows_from_parsed_paths": len(missed),
            "policy_severity_with_real_path": [row.severity for row in expected],
            "mode_changed_workflow_accepted_as_untouched": True,
        }


class RecordingGitHub(GitHubClient):
    def __init__(self) -> None:
        super().__init__(token="")
        self.posts: list[dict[str, object]] = []

    async def get_pull(self, *args, **kwargs):
        return {"head": {"sha": "b" * 40}}

    async def post(self, path, **kwargs):
        self.posts.append(kwargs.get("json", {}))
        return {}


async def status_probe() -> list[dict[str, object]]:
    gh = RecordingGitHub()
    ctx = make_tool_context(Path.cwd(), trust_tier="trusted", github=gh)
    ctx.payload.status_checks = True
    primary_repo_state(ctx.tool_state).checkout_sha = "a" * 40
    ctx.tool_state.approval = ApprovalRecord(would_approve=True, sha="a" * 40)
    # This probe tests publication of an already-decided packet, not approval inference.
    packet = NS(
        findings=(),
        run_health=None,
        self_assessment=None,
        coverage=None,
        decision=NS(verdict="success", reason="synthetic reviewed commit"),
    )
    with patch("mergecraft.utils.status_checks._triage_lines", return_value=[]):
        await report_status_checks(ctx, run_succeeded=True, packet=packet)
    rows = [{key: row.get(key) for key in ("name", "head_sha", "conclusion")} for row in gh.posts]
    assert rows[0]["head_sha"] == "a" * 40
    assert rows[1]["head_sha"] == "b" * 40
    assert rows[1]["conclusion"] == "success"
    return rows


async def budget_probe() -> dict[str, int]:
    base = RepoSettings.model_validate({"runBounds": {"tokenBudget": 100}})
    head = RepoSettings.model_validate({"runBounds": {"tokenBudget": 1_000_000}})
    ctx = make_tool_context(Path.cwd(), trust_tier="untrusted")
    ctx.budget_tracker = BudgetTracker(bounds=resolve_run_bounds(settings=base, env={}))
    ctx.repo_settings_snapshot = NS(settings=base, operator_owned=True)
    with (
        patch("mergecraft.config.settings.load_repo_settings", return_value=head),
        patch(
            "mergecraft.findings.ledger.hydrate_finding_ledger_from_progress_comment",
            new=AsyncMock(),
        ),
        patch.dict(os.environ, {}, clear=True),
    ):
        await hydrate_review_context(ctx, round_index=1)
    result = {
        "snapshot_token_budget": base.run_bounds.token_budget,
        "live_token_budget": ctx.budget_tracker.bounds.token_budget,
    }
    assert result == {"snapshot_token_budget": 100, "live_token_budget": 1_000_000}
    return result


async def ghes_probe() -> list[str]:
    seen: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, json={"data": {"viewer": {"login": "synthetic"}}})

    async with httpx.AsyncClient(
        base_url="https://ghe.example/api/v3", transport=httpx.MockTransport(handler)
    ) as transport:
        client = GitHubClient(
            token="synthetic", base_url="https://ghe.example/api/v3", client=transport
        )
        await client.get_repo("acme", "demo")
        await client.graphql("query { viewer { login } }")
    assert seen[-1] == "https://ghe.example/api/v3/graphql"
    return seen


def analyzer_union_probe() -> list[str]:
    from mergecraft.analyzers.finding import make_finding
    from mergecraft.mcp.analyzers import _store_run_state
    from mergecraft.mcp.tool_state import AnalyzerRunState, analyzer_run_key

    ctx = make_tool_context(Path.cwd(), trust_tier="trusted")
    for severity, paths in (("Minor", ["src/a.py"]), ("Major", ["src/a.py", "src/b.py"])):
        finding = make_finding(
            tool="synthetic-" + severity,
            rule_id="rule-" + severity,
            category="Functional Correctness",
            severity=severity,
            confidence="certain",
            message="same normalized diagnostic",
            path="src/a.py",
            start_line=1,
            end_line=1,
            source="analyzer",
            introduced_by_pr="true",
        )
        key = analyzer_run_key(
            repo_root=Path.cwd(),
            changed_files=paths,
            tier="trusted",
            shell="restricted",
            mode="Review",
            inline_budget=10,
            offline=False,
            base_ref="main",
            diff_text="fixture",
        )
        _store_run_state(
            ctx, AnalyzerRunState(ran=True, findings=[finding.model_dump()], covered_scope=key)
        )
    severities = [row["severity"] for row in ctx.tool_state.analyzer_run.findings]
    assert severities == ["Minor"], severities
    return severities


async def main() -> None:
    event = {
        "pull_request": {
            "head": {"repo": {"full_name": "acme/fork", "id": 42, "fork": True}},
            "base": {"repo": {"full_name": "acme/fork", "id": 42, "fork": True}},
        }
    }
    result = {
        "new_spaced_paths": spaced_diff_probe(),
        "prior_status_new_head": await status_probe(),
        "prior_budget_hydration": await budget_probe(),
        "prior_same_repo_fork_misclassification": is_fork_pull_request(event),
        "new_ghes_urls": await ghes_probe(),
        "prior_severity_residual_scope_union": analyzer_union_probe(),
    }
    assert result["prior_same_repo_fork_misclassification"] is True
    print(json.dumps(result, indent=2))  # noqa: T201 -- probe output is the script's purpose


if __name__ == "__main__":
    asyncio.run(main())
