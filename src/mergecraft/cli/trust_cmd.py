"""``mergecraft trust`` — inspect and configure operator trust policy (plan 13 W9)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import typer

from mergecraft.agents.codex import CODEX_SANDBOX_ENV, CODEX_SANDBOX_UNSANDBOXED
from mergecraft.cli.consoles import err_console as console
from mergecraft.cli.errors import cli_bail
from mergecraft.cli.provider_cmd import _config_path, _load_config_dict
from mergecraft.config.io import write_config_dict
from mergecraft.config.settings_snapshot import capture_repo_settings_snapshot
from mergecraft.config.trust_policy import (
    AGENT_SANDBOX_LEVELS,
    bound_head_sha,
    default_branch_from_event,
    resolve_agent_sandbox_decision,
    resolve_trust_policy,
)

app = typer.Typer(
    name="trust",
    help="Inspect and configure mergeCraft trust policy for this repository.",
    no_args_is_help=True,
)

_SELF_REVIEW_LEVELS: frozenset[str] = frozenset({"off", "analyzers", "full"})
_APPROVAL_AUTHORITY_FLAG = "--i-understand-this-grants-approval-authority"
_SAME_REPO_SANDBOX_FLAG = "--i-understand-same-repo-sandbox"


def _effective_event_for_cli() -> dict[str, Any]:
    """Same-repo ``pull_request_target`` is the knob's primary surface."""
    return {"pull_request": {"head": {"repo": {"fork": False, "full_name": "local/repo"}}}}


def _operator_override_requested() -> bool:
    raw = os.environ.get(CODEX_SANDBOX_ENV, "").strip().lower()
    return raw == CODEX_SANDBOX_UNSANDBOXED


@app.command("show")
def show_cmd(
    cwd: Path = typer.Option(Path("."), "--cwd", help="Repository root to inspect."),
) -> None:
    """Show the effective trust policy, level, and resolution source."""
    target = cwd.resolve()
    event = _effective_event_for_cli()
    event_name = "pull_request_target"
    snapshot = capture_repo_settings_snapshot(root=target)
    policy = resolve_trust_policy(
        event=event,
        config_root=target,
        event_name=event_name,
        settings_snapshot=snapshot,
    )
    head_sha = bound_head_sha(event, event_name=event_name) or "cli-inspect"
    sandbox = resolve_agent_sandbox_decision(
        event=event,
        event_name=event_name,
        config_root=target,
        settings_snapshot=snapshot,
        head_sha=head_sha,
        default_branch=default_branch_from_event(event),
        operator_override_requested=_operator_override_requested(),
    )
    console.print(f"selfReview level: {policy.level}")
    console.print(f"execution trust: {policy.execution_trust}")
    console.print(f"authority trust: {policy.authority_trust}")
    console.print(f"resolved from: {policy.resolved_from}")
    console.print(f"config hash: {policy.config_hash or '(no config file)'}")
    console.print(f"agentSandbox tier: {sandbox.configured_tier}")
    console.print(f"agentSandbox resolved from: {sandbox.resolved_from}")
    honoured = "granted" if sandbox.honour else "refused"
    console.print(f"agentSandbox resolved answer for this run: {honoured} ({sandbox.reason})")


@app.command("set-self-review")
def set_self_review_cmd(
    level: str = typer.Argument(..., help="off | analyzers | full"),
    cwd: Path = typer.Option(Path("."), "--cwd", help="Repository root to update."),
    i_understand_approval_authority: bool = typer.Option(
        False,
        _APPROVAL_AUTHORITY_FLAG,
        help="Required when setting full — grants approval authority on same-repo PRT.",
    ),
) -> None:
    """Write ``trust.selfReview`` to the committed config at ``--cwd``."""
    normalized = level.strip().lower()
    if normalized not in _SELF_REVIEW_LEVELS:
        cli_bail(f"invalid level {level!r} — expected off, analyzers, or full")

    target = cwd.resolve()
    config_path = _config_path(target)
    data = _load_config_dict(config_path)

    if normalized == "full":
        if not i_understand_approval_authority:
            cli_bail(
                "full requires "
                f"{_APPROVAL_AUTHORITY_FLAG} — this grants approval authority "
                "on same-repo pull_request_target and opts out of the D14/#200 separation"
            )
        console.print(
            "WARNING: trust.selfReview=full grants approval authority to self-review "
            "on same-repo pull_request_target. Real GitHub APPROVE for merge still "
            "flows through mergecraft-approve.yml when configured."
        )

    trust_block = data.get("trust")
    if not isinstance(trust_block, dict):
        trust_block = {}
    trust_block["selfReview"] = normalized
    data["trust"] = trust_block
    try:
        write_config_dict(config_path, data)
    except ValueError as exc:
        cli_bail(str(exc))
    console.print(f"updated {config_path}: trust.selfReview={normalized}")


@app.command("set-agent-sandbox")
def set_agent_sandbox_cmd(
    tier: str = typer.Argument(..., help="never | merged-only | dispatch | same-repo"),
    cwd: Path = typer.Option(Path("."), "--cwd", help="Repository root to update."),
    i_understand_same_repo_sandbox: bool = typer.Option(
        False,
        _SAME_REPO_SANDBOX_FLAG,
        help="Required when loosening to same-repo — grants override on any non-fork head.",
    ),
) -> None:
    """Write ``trust.agentSandbox`` to the committed config at ``--cwd``."""
    normalized = tier.strip().lower()
    if normalized not in AGENT_SANDBOX_LEVELS:
        cli_bail(f"invalid tier {tier!r} — expected never, merged-only, dispatch, or same-repo")

    target = cwd.resolve()
    config_path = _config_path(target)
    data = _load_config_dict(config_path)
    trust_block = data.get("trust")
    if not isinstance(trust_block, dict):
        trust_block = {}
    current = str(trust_block.get("agentSandbox", "dispatch")).strip().lower()

    if normalized == "same-repo" and current != "same-repo":
        if not i_understand_same_repo_sandbox:
            cli_bail(
                "same-repo requires "
                f"{_SAME_REPO_SANDBOX_FLAG} — this grants Codex sandbox override "
                "on any non-fork head, including same-repo pull_request_target"
            )
        console.print(
            "WARNING: trust.agentSandbox=same-repo grants the Codex sandbox override "
            f"({CODEX_SANDBOX_ENV}={CODEX_SANDBOX_UNSANDBOXED}) on any non-fork head. "
            "Fork heads always refuse."
        )

    trust_block["agentSandbox"] = normalized
    data["trust"] = trust_block
    try:
        write_config_dict(config_path, data)
    except ValueError as exc:
        cli_bail(str(exc))
    console.print(f"updated {config_path}: trust.agentSandbox={normalized}")


__all__ = ["app"]
