"""``mergecraft gha`` — run main(); also ``gha token [--post]``."""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

import typer
from loguru import logger

from mergecraft.analyzers.redact import redact_secrets
from mergecraft.cli.consoles import err_console as console
from mergecraft.cli.exits import (
    CLI_CONFIGURATION_EXIT_CODE,
)

if TYPE_CHECKING:
    from mergecraft.run_outcome import RunOutcome

app = typer.Typer(
    help="Run the GitHub Action runtime flow.",
    invoke_without_command=True,
    no_args_is_help=False,
)

STATE_TOKEN = "token"
_STATE_ENV = "STATE_token"


def _set_failed(message: str) -> None:
    console.print(f"::error::{message}")
    logger.error("{}", message)
    raise typer.Exit(CLI_CONFIGURATION_EXIT_CODE)


def _save_state(name: str, value: str) -> None:
    state_file = os.environ.get("GITHUB_STATE")
    if state_file:
        with open(state_file, "a", encoding="utf-8") as fh:
            fh.write(f"{name}={value}\n")
    os.environ[f"STATE_{name}"] = value


def _get_state(name: str) -> str:
    return os.environ.get(f"STATE_{name}", "") or os.environ.get(
        _STATE_ENV if name == STATE_TOKEN else f"STATE_{name}", ""
    )


def _set_output(name: str, value: str, *, mask: bool = False) -> None:
    """Write a step output. Never ``::add-mask::`` multiline values (H1 / Final).

    GitHub's add-mask is line-oriented; masking a pretty-printed JSON body only
    registers the first line (often ``{``) and leaves the rest in the log.
    Non-secret outputs (``result``, ``evidence_packet``) default to ``mask=False``.
    """
    out_file = os.environ.get("GITHUB_OUTPUT")
    if out_file:
        # Multi-line values must use the heredoc form; a bare `name=value` with
        # newlines makes the runner reject the file command ("Invalid format")
        # and fail the step. Pick a delimiter that cannot occur in the value.
        with open(out_file, "a", encoding="utf-8") as fh:
            if "\n" in value:
                delimiter = f"ghadelimiter_{uuid.uuid4().hex}"
                while delimiter in value:
                    delimiter = f"ghadelimiter_{uuid.uuid4().hex}"
                fh.write(f"{name}<<{delimiter}\n{value}\n{delimiter}\n")
            else:
                fh.write(f"{name}={value}\n")
    if mask and "\n" not in value and value:
        console.print(f"::add-mask::{value}")


def _structured_failure_result(outcome: RunOutcome, message: str) -> str:
    """Render the ``result`` output payload for a failed run (W5.3, ``#9``).

    JSON, not just ``::error::`` + exit 1, so a workflow step can branch on
    ``outcome`` / ``error.code`` without string-matching the human-readable
    message. ``error.code`` is a pure function of the outcome (stable across
    releases); ``error.message`` is redacted the same way analyzer output is
    (``analyzers.redact.redact_secrets``) before it ever reaches the output
    file, which GitHub echoes back into logs.
    """
    from mergecraft.run_outcome import error_code_for_outcome

    payload = {
        "outcome": outcome.value,
        "error": {
            "code": error_code_for_outcome(outcome),
            "message": redact_secrets(message),
        },
    }
    return json.dumps(payload)


def _write_evidence_packet_output(packet_path: str) -> None:
    """Wire the declared ``evidence_packet`` output to the packet on disk (W5.4, ``#47``/``#96``).

    The packet was already written by ``emit_run_packet``; this only has to
    read it back and hand it to ``_set_output`` — the existing UUID-heredoc
    form already handles a multiline JSON body correctly (``#38``), so no new
    output-writing path is introduced.
    """
    try:
        packet_json = Path(packet_path).read_text(encoding="utf-8")
    except OSError as err:
        logger.warning("evidence_packet output: could not read {} — {}", packet_path, err)
        return
    _set_output("evidence_packet", packet_json)


async def _run_main() -> None:
    from mergecraft.main import RunOutcome, main

    result = await main()
    if result.evidence_packet_path:
        _write_evidence_packet_output(result.evidence_packet_path)
    # The GHA output file is the one surface that needs the bare code: the enum
    # is what every other consumer reads.
    diagnostic = result.verdict_diagnostic
    _set_output("verdict_diagnostic", diagnostic.value if diagnostic is not None else "")
    if not result.success:
        outcome = result.outcome or RunOutcome.infra_error
        error_message = result.error or "agent execution failed"
        _set_output("result", _structured_failure_result(outcome, error_message))
        _set_failed(f"action failed: {error_message}")
    if result.result:
        _set_output("result", result.result)


async def _token_main() -> None:
    from mergecraft.utils.token import acquire_installation_token

    repos_input = os.environ.get("INPUT_REPOS", "").strip()
    additional = [r.strip() for r in repos_input.split(",") if r.strip()] if repos_input else []
    token = await acquire_installation_token(repos=additional or None)
    _set_output("token", token, mask=True)
    _save_state(STATE_TOKEN, token)
    scope = f"current repo + {', '.join(additional)}" if additional else "current repo only"
    console.print(f"» installation token acquired ({scope})")


async def _token_post() -> None:
    from mergecraft.utils.token import revoke_installation_token

    token = _get_state(STATE_TOKEN)
    if not token:
        logger.debug("no token found in state, skipping revocation")
        return
    await revoke_installation_token(token)
    console.print("» installation token revoked")


@app.callback(invoke_without_command=True)
def gha_root(ctx: typer.Context) -> None:
    """Run ``main()`` (default when invoked as the action entrypoint)."""
    if ctx.invoked_subcommand is not None:
        return
    try:
        asyncio.run(_run_main())
    except typer.Exit:
        raise
    except Exception as error:
        _set_failed(str(error))


@app.command("token")
def gha_token(
    post: bool = typer.Option(
        False,
        "--post",
        help="Revoke the previously-acquired token (post-step usage only).",
    ),
) -> None:
    """Acquire a GitHub App installation token, or revoke it with ``--post``."""
    try:
        if post:
            asyncio.run(_token_post())
        else:
            asyncio.run(_token_main())
    except typer.Exit:
        raise
    except Exception as error:
        _set_failed(str(error))
