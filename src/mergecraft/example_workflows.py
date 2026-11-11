"""Render the consumer workflow templates from one shared source.

Module: mergecraft.example_workflows
Depends: json, importlib.resources, mergecraft.pins

Exports:
    substitute — apply the shared placeholders to a template body.
    minimal_template_text — the packaged minimal workflow template.
    render_minimal_workflow — the minimal workflow with the current pins applied.

``mergecraft init`` and ``scripts/render_example_workflows.py`` both render the minimal
workflow from ``data/example_workflows/minimal.yml.tpl``, so the scaffold and
``examples/workflows/mergecraft.yml`` cannot drift apart.
"""

from __future__ import annotations

import json
from importlib.resources import files

from mergecraft.pins import load_example_defaults

MINIMAL_TEMPLATE_RESOURCE = "example_workflows/minimal.yml.tpl"


def minimal_template_text() -> str:
    """Return the packaged minimal workflow template, placeholders unresolved."""
    return files("mergecraft.data").joinpath(MINIMAL_TEMPLATE_RESOURCE).read_text(encoding="utf-8")


def substitute(
    template_text: str, *, variant: str, defaults: dict[str, str], source: str = "template"
) -> str:
    """Apply shared placeholders to a template body (``variant``: minimal or hardened)."""
    pin_key = "action_pin_hardened" if variant == "hardened" else "action_pin_minimal"
    replacements = {
        "__ACTION_REPO__": defaults["action_repo"],
        "__ACTION_PIN__": defaults[pin_key],
        "__ACTION_SHA__": defaults["action_sha_minimal"],
        "__CHECKOUT_SHA__": defaults["checkout_sha"],
        "__CI_JOB_PREFIX__": json.dumps(defaults["ci_job_prefix"]),
        "__BASE_BRANCHES__": defaults["base_branches"],
    }
    rendered = template_text
    for token, value in replacements.items():
        rendered = rendered.replace(token, value)
    missing = [token for token in replacements if token in rendered]
    if missing:
        msg = f"{source}: unresolved placeholders: {', '.join(missing)}"
        raise ValueError(msg)
    if not rendered.endswith("\n"):
        rendered += "\n"
    return rendered


def render_minimal_workflow(defaults: dict[str, str] | None = None) -> str:
    """Render the minimal consumer workflow (the ``mergecraft init`` scaffold)."""
    values = defaults if defaults is not None else load_example_defaults()
    return substitute(
        minimal_template_text(),
        variant="minimal",
        defaults=values,
        source=MINIMAL_TEMPLATE_RESOURCE,
    )
