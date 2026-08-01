"""``mergecraft gha`` — run main(); also ``gha token [--post]``."""

from __future__ import annotations

import asyncio
import os
import uuid

import typer
from loguru import logger
from rich.console import Console

app = typer.Typer(
    help="Run the GitHub Action runtime flow.",
    invoke_without_command=True,
    no_args_is_help=False,
)
console = Console(stderr=True)

STATE_TOKEN = "token"
_STATE_ENV = "STATE_token"


def _set_failed(message: str) -> None:
    console.print(f"::error::{message}")
    logger.error("{}", message)
    raise typer.Exit(1)


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


def _set_output(name: str, value: str) -> None:
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
    # also mask
    console.print(f"::add-mask::{value}")


async def _run_main() -> None:
    from mergecraft.main import main

    result = await main()
    if not result.success:
        _set_failed(f"action failed: {result.error or 'agent execution failed'}")
    if result.result:
        _set_output("result", result.result)


async def _token_main() -> None:
    from mergecraft.utils.token import acquire_installation_token

    repos_input = os.environ.get("INPUT_REPOS", "").strip()
    additional = [r.strip() for r in repos_input.split(",") if r.strip()] if repos_input else []
    token = await acquire_installation_token(repos=additional or None)
    _set_output("token", token)
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
