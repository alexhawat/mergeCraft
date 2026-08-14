#!/usr/bin/env python3
"""Regenerate README's action-input, action-output, and CLI reference tables.

Module: scripts.gen_reference_docs
Depends: argparse, difflib, inspect, re, sys, typing, pathlib, yaml,
    mergecraft.cli.app

The two reference tables in ``README.md`` (the ``action.yml`` "full input
list" and the ``## CLI`` command table) are hand-maintained prose that drifts
from the live sources — see the ``issues-showcase-readiness`` wave plan, PR
G2. This script derives both from the live sources (``action.yml`` for
inputs/outputs, the live Typer ``app`` object for CLI commands — never a
subprocess) and splices them into ``README.md`` between HTML sentinel
comments, so the tables can be regenerated (default) or checked for drift
(``--check``) without hand-editing.

Exports:
    main — regenerate (default) or ``--check`` the README reference tables.
"""

from __future__ import annotations

import argparse
import difflib
import inspect
import re
import sys
import typing
from pathlib import Path
from typing import Any

import typer
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
ACTION_YML_PATH = REPO_ROOT / "action.yml"
README_PATH = REPO_ROOT / "README.md"

_ACTION_INPUTS_BEGIN = "<!-- BEGIN:action-inputs -->"
_ACTION_INPUTS_END = "<!-- END:action-inputs -->"
_ACTION_OUTPUTS_BEGIN = "<!-- BEGIN:action-outputs -->"
_ACTION_OUTPUTS_END = "<!-- END:action-outputs -->"
_CLI_COMMANDS_BEGIN = "<!-- BEGIN:cli-commands -->"
_CLI_COMMANDS_END = "<!-- END:cli-commands -->"

CommandPath = tuple[str, ...]

# ---------------------------------------------------------------------------
# shared text helpers
# ---------------------------------------------------------------------------


def _first_paragraph(text: str) -> str:
    """Return the first blank-line-delimited paragraph of ``text``, collapsed to one line."""
    paragraph = text.strip().split("\n\n", 1)[0]
    return " ".join(paragraph.split())


def _md_cell(text: str) -> str:
    """Make ``text`` safe as one markdown table cell: single backticks, no bare pipes."""
    collapsed = _first_paragraph(text).replace("``", "`")
    return collapsed.replace("|", "\\|")


# ---------------------------------------------------------------------------
# action.yml -> action-inputs / action-outputs tables
# ---------------------------------------------------------------------------


def _load_action_yml() -> dict[str, Any]:
    data = yaml.safe_load(ACTION_YML_PATH.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        msg = f"{ACTION_YML_PATH}: did not parse as a mapping"
        raise TypeError(msg)
    return data


def _render_default_cell(spec: dict[str, Any]) -> str:
    """Render the literal ``action.yml`` ``default:`` value, not any behavioural default.

    ``_(unset)_`` means the input has no ``default:`` key at all (required prose
    default lives only in the description, if anywhere). ``_(empty)_`` means an
    explicit ``default: ""`` — distinct from having no default key.
    """
    if "default" not in spec:
        return "_(unset)_"
    default = str(spec["default"])
    if default == "":
        return "_(empty)_"
    return f"`{default}`"


def _render_action_inputs(inputs: dict[str, dict[str, Any]]) -> str:
    lines = [
        "The full input list:",
        "",
        "| Input | Default | Description |",
        "|-------|---------|-------------|",
    ]
    for name in sorted(inputs):
        spec = inputs[name] or {}
        default_cell = _render_default_cell(spec)
        description = _md_cell(str(spec.get("description", "")))
        lines.append(f"| `{name}` | {default_cell} | {description} |")
    lines.append("")
    return "\n".join(lines)


def _render_action_outputs(outputs: dict[str, dict[str, Any]]) -> str:
    lines = [
        "| Output | Description |",
        "|--------|-------------|",
    ]
    for name in sorted(outputs):
        spec = outputs[name] or {}
        description = _md_cell(str(spec.get("description", "")))
        lines.append(f"| `{name}` | {description} |")
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# live Typer app -> CLI command table
# ---------------------------------------------------------------------------


def _walk_typer_commands(
    app: typer.Typer, prefix: CommandPath = ()
) -> list[tuple[CommandPath, Any]]:
    """Recursively collect every leaf command's path + callback from a Typer app.

    Mirrors ``tests/docs/test_reference_docs.py::_walk_typer_commands`` (never
    invoke the CLI as a subprocess to discover commands — walk the live
    ``registered_commands`` / ``registered_groups`` objects).
    """
    commands: list[tuple[CommandPath, Any]] = []
    for command in app.registered_commands:
        name = command.name
        if name is None and command.callback is not None:
            name = command.callback.__name__.replace("_", "-")
        if not name:
            msg = f"unnamed command under {prefix}"
            raise ValueError(msg)
        commands.append(((*prefix, name), command.callback))
    for group in app.registered_groups:
        if not group.name or group.typer_instance is None:
            msg = f"malformed group under {prefix}: {group.name!r}"
            raise ValueError(msg)
        commands.extend(_walk_typer_commands(group.typer_instance, (*prefix, group.name)))
    return commands


def _typer_info(param: inspect.Parameter, hint: Any) -> Any:
    """Return the ``ArgumentInfo``/``OptionInfo`` behind a Typer parameter.

    Handles both the legacy ``name: T = typer.Option(...)`` style (the info
    object *is* the parameter default) and the modern
    ``name: Annotated[T, typer.Option(...)]`` style (the info object is
    embedded in the annotation's metadata instead — ``hint`` is the
    *resolved* annotation from ``typing.get_type_hints``, since
    ``from __future__ import annotations`` leaves ``param.annotation`` as an
    unresolved string in some, but not all, observed cases).
    """
    if isinstance(param.default, (typer.models.ArgumentInfo, typer.models.OptionInfo)):
        return param.default
    for arg in typing.get_args(hint):
        if isinstance(arg, (typer.models.ArgumentInfo, typer.models.OptionInfo)):
            return arg
    return None


def _is_required(param: inspect.Parameter, info: Any) -> bool:
    if param.default is inspect.Parameter.empty:
        return True
    return bool(
        isinstance(info, (typer.models.ArgumentInfo, typer.models.OptionInfo))
        and info.default is ...
    )


def _invocation_suffix(callback: Any) -> str:
    """Best-effort trailing placeholder tokens for a command's required params.

    Only ever appends a token pattern the README test's parser
    (``_parse_cli_invocation``) can strip back off cleanly: a run of required
    positional ``<placeholder>`` tokens, or a single ``--flag PLACEHOLDER``
    when there is exactly one required option and no required positional
    argument. Commands with several required options (e.g. ``eval add``) are
    documented bare — the parser only strips *one* trailing flag+value pair,
    so chaining several would leave a bogus token stuck to the command path.
    """
    sig = inspect.signature(callback)
    try:
        hints = typing.get_type_hints(callback, include_extras=True)
    except Exception:  # pragma: no cover - defensive; every real command resolves cleanly
        hints = {}
    arg_placeholders: list[str] = []
    required_options: list[tuple[Any, inspect.Parameter, Any]] = []
    for name, param in sig.parameters.items():
        hint = hints.get(name, param.annotation)
        info = _typer_info(param, hint)
        if info is None or not _is_required(param, info):
            continue
        if isinstance(info, typer.models.ArgumentInfo):
            arg_placeholders.append(f"<{name.replace('_', '-')}>")
        else:
            required_options.append((info, param, hint))
    if arg_placeholders:
        return " " + " ".join(arg_placeholders)
    if len(required_options) == 1:
        info, param, hint = required_options[0]
        flag = info.param_decls[0] if info.param_decls else f"--{param.name.replace('_', '-')}"
        placeholder = "N" if "int" in str(hint) else param.name.upper()
        return f" {flag} {placeholder}"
    return ""


def _cli_row(path: CommandPath, callback: Any) -> str:
    invocation = "mergecraft " + " ".join(path) + _invocation_suffix(callback)
    summary = _md_cell(callback.__doc__ or "") if callback is not None else ""
    return f"| `{invocation}` | {summary} |"


def _render_cli_table(commands: list[tuple[CommandPath, Any]]) -> str:
    lines = ["| Command | Description |", "|---------|-------------|"]
    for path, callback in sorted(commands, key=lambda item: item[0]):
        lines.append(_cli_row(path, callback))
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# sentinel splicing
# ---------------------------------------------------------------------------


def _splice(text: str, begin: str, end: str, content: str, *, required: bool) -> str:
    """Replace the text between a ``<!-- BEGIN:x -->`` / ``<!-- END:x -->`` pair.

    When ``required`` is False and the sentinel pair is absent, ``text`` is
    returned unchanged — used for the action-outputs table, which is not part
    of the generator's frozen scratch-fixture contract (``README.md`` in the
    real repo carries the sentinel; ad-hoc scratch fixtures may not).
    """
    pattern = re.compile(re.escape(begin) + r"\n.*?" + re.escape(end), re.DOTALL)
    if not pattern.search(text):
        if required:
            msg = f"{README_PATH}: sentinel pair not found: {begin} / {end}"
            raise SystemExit(msg)
        return text
    replacement = f"{begin}\n{content}{end}"
    return pattern.sub(lambda _match: replacement, text, count=1)


def _generate(
    action_data: dict[str, Any], readme_text: str, commands: list[tuple[CommandPath, Any]]
) -> str:
    inputs = dict(action_data.get("inputs") or {})
    outputs = dict(action_data.get("outputs") or {})
    text = readme_text
    text = _splice(
        text, _ACTION_INPUTS_BEGIN, _ACTION_INPUTS_END, _render_action_inputs(inputs), required=True
    )
    text = _splice(
        text,
        _ACTION_OUTPUTS_BEGIN,
        _ACTION_OUTPUTS_END,
        _render_action_outputs(outputs),
        required=False,
    )
    return _splice(
        text, _CLI_COMMANDS_BEGIN, _CLI_COMMANDS_END, _render_cli_table(commands), required=True
    )


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """Regenerate (default) or ``--check`` README's action/CLI reference tables."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit non-zero (with a unified diff) when README drifts from action.yml / the live CLI.",
    )
    args = parser.parse_args(argv)

    # Imported here (not at module scope) so ``--check``/write always reflect
    # whatever ``mergecraft.cli.app`` looks like right now — and so a bare
    # ``python -c "import scripts.gen_reference_docs"`` never has an import-time
    # side effect of loading the whole CLI app.
    from mergecraft.cli.app import app as root_app

    action_data = _load_action_yml()
    commands = _walk_typer_commands(root_app)
    readme_text = README_PATH.read_text(encoding="utf-8")
    generated = _generate(action_data, readme_text, commands)

    if args.check:
        if generated == readme_text:
            print(f"{README_PATH.name}: reference tables match action.yml / the live CLI")
            return 0
        diff = difflib.unified_diff(
            readme_text.splitlines(keepends=True),
            generated.splitlines(keepends=True),
            fromfile=str(README_PATH),
            tofile=f"{README_PATH} (generated)",
        )
        sys.stdout.writelines(diff)
        print(
            f"{README_PATH.name}: reference tables drifted from action.yml / the live CLI"
            " (run: make reference-docs)",
            file=sys.stderr,
        )
        return 1

    README_PATH.write_text(generated, encoding="utf-8")
    print(f"wrote {README_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
