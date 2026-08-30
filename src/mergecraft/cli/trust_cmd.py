"""``mergecraft trust`` — inspect and configure operator trust policy (plan 13 W9)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import typer

from mergecraft.cli.consoles import err_console as console
from mergecraft.cli.errors import cli_bail
from mergecraft.cli.provider_cmd import _config_path, _load_config_dict
from mergecraft.config.io import write_config_dict
from mergecraft.config.settings_snapshot import capture_repo_settings_snapshot
from mergecraft.config.trust_policy import resolve_trust_policy

app = typer.Typer(
    name="trust",
    help="Inspect and configure mergeCraft trust policy for this repository.",
    no_args_is_help=True,
)

_SELF_REVIEW_LEVELS: frozenset[str] = frozenset({"off", "analyzers", "full"})
_APPROVAL_AUTHORITY_FLAG = "--i-understand-this-grants-approval-authority"


def _effective_event_for_cli() -> dict[str, Any]:
    """Same-repo ``pull_request_target`` is the knob's primary surface."""
    return {"pull_request": {"head": {"repo": {"fork": False, "full_name": "local/repo"}}}}


@app.command("show")
def show_cmd(
    cwd: Path = typer.Option(Path("."), "--cwd", help="Repository root to inspect."),
) -> None:
    """Show the effective trust policy, level, and resolution source."""
    target = cwd.resolve()
    snapshot = capture_repo_settings_snapshot(root=target)
    policy = resolve_trust_policy(
        event=_effective_event_for_cli(),
        config_root=target,
        event_name="pull_request_target",
        settings_snapshot=snapshot,
    )
    console.print(f"selfReview level: {policy.level}")
    console.print(f"execution trust: {policy.execution_trust}")
    console.print(f"authority trust: {policy.authority_trust}")
    console.print(f"resolved from: {policy.resolved_from}")
    console.print(f"config hash: {policy.config_hash or '(no config file)'}")


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
    write_config_dict(config_path, data)
    console.print(f"updated {config_path}: trust.selfReview={normalized}")


__all__ = ["app"]
