"""Typer group that bootstraps global CLI colour before ``--help`` renders."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

from typer.core import TyperGroup

from mergecraft.cli.global_surface import bootstrap_cli_surface_from_argv

if TYPE_CHECKING:
    import click


class MergecraftTyperGroup(TyperGroup):
    """Apply #342 colour policy before Rich help formatting."""

    def make_context(
        self,
        info_name: str | None,
        args: list[str],
        parent: click.Context | None = None,
        **extra: Any,
    ) -> click.Context:
        bootstrap_cli_surface_from_argv(args, env=os.environ)
        return super().make_context(info_name, args, parent=parent, **extra)
