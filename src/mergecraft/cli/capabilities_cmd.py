"""``mergecraft capabilities`` — review-only capability manifest (#350 / D10)."""

from __future__ import annotations

from typing import Final, TypedDict

import typer  # noqa: TC002 — Typer injects Context from this annotation at runtime
from rich.table import Table

from mergecraft.cli.consoles import err_console as console
from mergecraft.cli.global_surface import emit_cli_json, wants_json_output
from mergecraft.modes import _MODE_DEFS

ALLOWED_CAPABILITIES: Final[tuple[str, ...]] = (
    "identify",
    "investigate",
    "verify",
    "explain",
    "prioritize",
    "suggest",
)
FORBIDDEN_CAPABILITIES: Final[tuple[str, ...]] = (
    "edit_source",
    "apply_fixes",
    "commit",
    "push",
    "open_code_changing_pr",
)


class CapabilitiesManifest(TypedDict):
    """Machine-readable review-only capability contract (no ``schema_version``)."""

    review_only: bool
    modes: list[str]
    allowed: list[str]
    forbidden: list[str]


def capabilities_manifest() -> CapabilitiesManifest:
    """Return the review-only capability manifest.

    JSON callers inherit ``schema_version`` from the global ``--format json``
    envelope; this payload must not include it.
    """
    return {
        "review_only": True,
        "modes": [name for name, _, _ in _MODE_DEFS],
        "allowed": list(ALLOWED_CAPABILITIES),
        "forbidden": list(FORBIDDEN_CAPABILITIES),
    }


def _render_table(manifest: CapabilitiesManifest) -> Table:
    table = Table(
        title="mergeCraft review-only capability manifest",
        show_header=True,
        header_style="bold",
    )
    table.add_column("field")
    table.add_column("value")
    table.add_row("review_only", "true")
    table.add_row("modes", ", ".join(manifest["modes"]))
    table.add_row("allowed", ", ".join(manifest["allowed"]))
    table.add_row("forbidden", ", ".join(manifest["forbidden"]))
    return table


def run(ctx: typer.Context) -> None:
    """Print the review-only capability manifest."""
    manifest = capabilities_manifest()
    if wants_json_output(ctx, json_flag=False):
        emit_cli_json(dict(manifest))
        return
    console.print(_render_table(manifest))


__all__ = [
    "ALLOWED_CAPABILITIES",
    "FORBIDDEN_CAPABILITIES",
    "capabilities_manifest",
    "run",
]
