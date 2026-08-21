"""``mergecraft profile`` — recommend a review profile from change risk (#369 / D10).

Additive Typer group. Does not fold profile select into the root callback.

Exports:
    app: Typer group registered as ``mergecraft profile``.
    recommend_cmd: Print the auto-selected profile for a risk band.
"""

from __future__ import annotations

import typer

from mergecraft.cli.errors import cli_bail
from mergecraft.cli.exits import CLI_USAGE_EXIT_CODE
from mergecraft.cli.global_surface import emit_cli_json, wants_json_output
from mergecraft.cli.profiles import select_profile_from_risk

app = typer.Typer(
    name="profile",
    help="Recommend a review profile from change risk.",
    no_args_is_help=True,
)


@app.command("recommend")
def recommend_cmd(
    ctx: typer.Context,
    risk: str = typer.Option(
        ...,
        "--risk",
        help="Change risk band used to auto-select a profile (trivial, low, medium, high, critical).",
    ),
) -> None:
    """Print the review profile auto-selected from ``--risk``."""
    try:
        profile = select_profile_from_risk(risk)
    except ValueError as exc:
        cli_bail(str(exc), code=CLI_USAGE_EXIT_CODE)
    payload = {"profile": profile.name, "risk": risk.strip().lower()}
    if wants_json_output(ctx, json_flag=False):
        emit_cli_json(payload)
        return
    typer.echo(profile.name)


__all__ = ["app", "recommend_cmd"]
