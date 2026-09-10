"""``mergecraft trust`` — inspect and configure operator trust policy (plan 13 W9)."""

from __future__ import annotations

import base64
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Protocol

import typer

from mergecraft.agents.codex import CODEX_SANDBOX_ENV, CODEX_SANDBOX_UNSANDBOXED
from mergecraft.cli.consoles import err_console as console
from mergecraft.cli.errors import cli_bail
from mergecraft.cli.provider_cmd import _config_path, _load_config_dict
from mergecraft.config.io import config_has_yaml_comments, write_config_dict
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
_SELF_REVIEW_LINE = re.compile(
    r"^([ \t]+)selfReview:[ \t]*(['\"]?)[A-Za-z0-9_-]+\2([ \t]*(?:#.*)?)?\s*$",
)
_TRUST_HEADER = re.compile(r"^([ \t]*)trust:\s*(?:#.*)?$")
_CONFIG_REL = ".mergecraft/config.yaml"


class GhRunner(Protocol):
    def __call__(self, args: list[str], *, input_text: str | None = None) -> str: ...


def _default_gh_runner(args: list[str], *, input_text: str | None = None) -> str:
    try:
        completed = subprocess.run(
            ["gh", *args],
            check=False,
            capture_output=True,
            text=True,
            input=input_text,
        )
    except OSError as exc:
        cli_bail(f"gh is required for --gh-apply: {exc}")
    if completed.returncode != 0:
        err = (completed.stderr or completed.stdout or "").strip()
        if "Not Found" in err or "HTTP 404" in err:
            return completed.stdout or '{"message":"Not Found"}'
        cli_bail(f"gh {' '.join(args)} failed: {err}")
    return completed.stdout


def patch_self_review_yaml(text: str, level: str) -> str:
    """Set ``trust.selfReview`` under the ``trust:`` block, preserving comments."""
    lines = text.splitlines(keepends=True)
    if not lines and text:
        lines = [text]
    in_trust = False
    trust_indent = 0
    replaced = False
    out: list[str] = []
    for line in lines:
        header = _TRUST_HEADER.match(line)
        if header:
            in_trust = True
            trust_indent = len(header.group(1))
            out.append(line)
            continue
        if in_trust:
            # strip(), not lstrip(" \t"): a bare "\n" survives lstrip and reads as
            # a dedent, so a blank line inside the block ended it early. The
            # existing key was then never replaced and the fallback regex
            # appended a second `selfReview:` to the same mapping — loaders that
            # keep the last duplicate resolved straight back to the old value.
            stripped = line.strip()
            indent = len(line) - len(line.lstrip(" \t"))
            if stripped and not stripped.startswith("#") and indent <= trust_indent:
                in_trust = False
            elif not replaced:
                match = _SELF_REVIEW_LINE.match(line)
                if match and indent > trust_indent:
                    comment = match.group(3) or ""
                    out.append(f'{match.group(1)}selfReview: "{level}"{comment}'.rstrip() + "\n")
                    replaced = True
                    continue
        out.append(line)
    if replaced:
        return "".join(out)
    if re.search(r"^trust:\s*(?:#.*)?$", text, flags=re.MULTILINE):
        return re.sub(
            r"^(trust:\s*(?:#.*)?)$",
            rf'\1\n  selfReview: "{level}"',
            text,
            count=1,
            flags=re.MULTILINE,
        )
    suffix = "" if text.endswith("\n") or not text else "\n"
    return f'{text}{suffix}trust:\n  selfReview: "{level}"\n'


def _gh_json(run: GhRunner, args: list[str], *, input_text: str | None = None) -> Any:
    raw = run(args, input_text=input_text)
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        cli_bail(f"gh {' '.join(args)} returned non-JSON: {exc}")


def _gh_optional_json(run: GhRunner, args: list[str], *, input_text: str | None = None) -> Any:
    raw = run(args, input_text=input_text)
    if not raw.strip() or "Not Found" in raw:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        cli_bail(f"gh {' '.join(args)} returned non-JSON: {exc}")
    if isinstance(data, dict) and data.get("message") == "Not Found":
        return None
    return data


def apply_self_review_on_default_branch(
    level: str,
    *,
    runner: GhRunner | None = None,
) -> str:
    """Open a default-branch PR that sets ``trust.selfReview`` for Actions (#616)."""
    run = runner or _default_gh_runner
    repo_info = _gh_json(run, ["repo", "view", "--json", "nameWithOwner,defaultBranchRef"])
    if not isinstance(repo_info, dict):
        cli_bail("gh repo view returned an unexpected payload")
    repo = str(repo_info.get("nameWithOwner") or "")
    default_ref = repo_info.get("defaultBranchRef")
    default_branch = ""
    if isinstance(default_ref, dict):
        default_branch = str(default_ref.get("name") or "")
    if not repo or not default_branch:
        cli_bail("could not resolve the repository default branch via gh")
    # _gh_optional_json, not _gh_json: the runner *returns* the 404 body, which
    # _gh_json parses into a dict, so the isinstance guard below never fired. The
    # run then continued with an empty sha and PUT a malformed blob, so the
    # operator got a 422 about the sha instead of the actionable fact — there is
    # no config on the default branch.
    payload = _gh_optional_json(
        run, ["api", f"repos/{repo}/contents/{_CONFIG_REL}?ref={default_branch}"]
    )
    if payload is None:
        cli_bail(
            f"{_CONFIG_REL} does not exist on {default_branch}; "
            f"commit one there before using --gh-apply"
        )
    if not isinstance(payload, dict):
        cli_bail(f"could not read default-branch {_CONFIG_REL}")
    content_b64 = str(payload.get("content") or "").replace("\n", "")
    blob_sha = str(payload.get("sha") or "")
    try:
        current = base64.b64decode(content_b64).decode("utf-8")
    except (ValueError, UnicodeDecodeError) as exc:
        cli_bail(f"could not decode default-branch {_CONFIG_REL}: {exc}")
    updated = patch_self_review_yaml(current, level)
    branch = f"mergecraft/trust-self-review-{level}"
    existing_branch = _gh_optional_json(run, ["api", f"repos/{repo}/git/ref/heads/{branch}"])
    if updated == current and existing_branch is None:
        cli_bail(f"default-branch {_CONFIG_REL} already has trust.selfReview={level}")
    if existing_branch is None:
        ref = _gh_json(run, ["api", f"repos/{repo}/git/ref/heads/{default_branch}"])
        head_sha = ""
        if isinstance(ref, dict):
            obj = ref.get("object")
            if isinstance(obj, dict):
                head_sha = str(obj.get("sha") or "")
        if not head_sha:
            cli_bail(f"could not resolve {default_branch} tip SHA")
        _gh_json(
            run,
            [
                "api",
                "-X",
                "POST",
                f"repos/{repo}/git/refs",
                "--input",
                "-",
            ],
            input_text=json.dumps({"ref": f"refs/heads/{branch}", "sha": head_sha}),
        )
    else:
        branch_file = _gh_json(run, ["api", f"repos/{repo}/contents/{_CONFIG_REL}?ref={branch}"])
        if isinstance(branch_file, dict) and branch_file.get("sha"):
            blob_sha = str(branch_file["sha"])
            current_on_branch = ""
            try:
                current_on_branch = base64.b64decode(
                    str(branch_file.get("content") or "").replace("\n", "")
                ).decode("utf-8")
            except (ValueError, UnicodeDecodeError):
                current_on_branch = ""
            updated = patch_self_review_yaml(current_on_branch or current, level)
    message = f"chore(trust): set selfReview={level} on {default_branch} for Actions"
    _gh_json(
        run,
        ["api", "-X", "PUT", f"repos/{repo}/contents/{_CONFIG_REL}", "--input", "-"],
        input_text=json.dumps(
            {
                "message": message,
                "content": base64.b64encode(updated.encode("utf-8")).decode("ascii"),
                "branch": branch,
                "sha": blob_sha,
            }
        ),
    )
    listed = _gh_optional_json(
        run,
        ["pr", "list", "--repo", repo, "--head", branch, "--json", "url"],
    )
    if isinstance(listed, list) and listed:
        first = listed[0]
        if isinstance(first, dict) and first.get("url"):
            return str(first["url"])
    pr_url = run(
        [
            "pr",
            "create",
            "--repo",
            repo,
            "--base",
            default_branch,
            "--head",
            branch,
            "--title",
            message,
            "--body",
            (
                "Updates default-branch `.mergecraft/config.yaml` so the next "
                f"`pull_request_target` run sees `trust.selfReview: {level}`.\n\n"
                "Fork floors are unchanged. This PR only writes the committed config."
            ),
        ]
    ).strip()
    return pr_url or branch


def _write_local_self_review(config_path: Path, data: dict[str, Any], level: str) -> None:
    """Write ``trust.selfReview`` locally, patching comments in place when present."""
    if config_has_yaml_comments(config_path) and config_path.is_file():
        patched = patch_self_review_yaml(config_path.read_text(encoding="utf-8"), level)
        config_path.write_text(patched, encoding="utf-8")
        return
    trust_block = data.get("trust")
    if not isinstance(trust_block, dict):
        trust_block = {}
    trust_block["selfReview"] = level
    data["trust"] = trust_block
    try:
        write_config_dict(config_path, data)
    except ValueError as exc:
        cli_bail(str(exc))


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
    gh_apply: bool = typer.Option(
        False,
        "--gh-apply",
        help="Also open a PR against the default branch so Actions/PRT see the change.",
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

    if gh_apply:
        pr_url = apply_self_review_on_default_branch(normalized)
        console.print(f"opened default-branch PR for Actions: {pr_url}")
    _write_local_self_review(config_path, data, normalized)
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


__all__ = ["app", "apply_self_review_on_default_branch", "patch_self_review_yaml"]
