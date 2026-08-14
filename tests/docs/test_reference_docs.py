"""G2 — README action/CLI reference tables vs. live ``action.yml``/CLI app (RED, G2.1).

Three separate audits found README/action.yml/CLI drift (issues-showcase-readiness
wave plan, PR G2): the README's "full input list" table documents 9 of 24 real
``action.yml`` inputs, neither declared output is documented anywhere, the CLI
table documents ``mergecraft traces <run-id>`` when the real registered command is
``mergecraft traces show <run-id>``, and whole CLI groups (``analyzers``, ``eval``,
``findings``, ``version``, ``gha token``, ``tracing logfire enable/disable``) are
undocumented. G2.2 (a later wave) adds ``scripts/gen_reference_docs.py`` to
regenerate both tables from the live sources between HTML sentinel comments and
wires a ``--check`` gate into ``make ci-static``; this suite is the RED contract
that wave implements against.

Every assertion here reads the *live* ``action.yml`` / live Typer ``app`` object
rather than hard-coding today's counts, so the suite stays correct as the code
evolves instead of re-encoding today's drift as magic numbers.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from mergecraft.cli.app import app as root_app
from mergecraft.cli.auth_cmd import app as auth_app
from tests.ci.workflow_support import REPO_ROOT

if TYPE_CHECKING:
    import pytest
    import typer

ACTION_YML = REPO_ROOT / "action.yml"
README = REPO_ROOT / "README.md"

# ---------------------------------------------------------------------------
# action.yml helpers
# ---------------------------------------------------------------------------


def _load_action_yml() -> dict[str, Any]:
    data = yaml.safe_load(ACTION_YML.read_text(encoding="utf-8"))
    assert isinstance(data, dict), "action.yml did not parse as a mapping"
    return data


def _action_inputs() -> dict[str, dict[str, Any]]:
    return dict(_load_action_yml().get("inputs") or {})


def _action_outputs() -> dict[str, dict[str, Any]]:
    return dict(_load_action_yml().get("outputs") or {})


def _readme_action_input_table() -> dict[str, str]:
    """Parse README's ``| Input | Default | Description |`` table.

    Returns ``{input_name: raw_default_cell_text}`` (the ``Default`` column,
    backticks and placeholder prose like ``_(empty)_`` left un-normalised —
    callers normalise per their own needs).
    """
    text = README.read_text(encoding="utf-8")
    match = re.search(r"The full input list:\n\n(\|.*\n(?:\|.*\n)+)", text)
    assert match, "README.md: could not locate 'The full input list:' action-input table"
    rows = match.group(1).splitlines()[2:]  # drop header + separator rows
    documented: dict[str, str] = {}
    for row in rows:
        cells = [cell.strip() for cell in row.strip().strip("|").split("|")]
        if len(cells) < 2:
            continue
        name = cells[0].strip("`")
        documented[name] = cells[1]
    return documented


# ---------------------------------------------------------------------------
# CLI-app helpers
# ---------------------------------------------------------------------------


def _walk_typer_commands(app: typer.Typer, prefix: tuple[str, ...] = ()) -> set[tuple[str, ...]]:
    """Recursively collect every leaf command's full path from a Typer app.

    Walks ``registered_commands`` (leaves) and ``registered_groups``
    (``add_typer`` sub-apps, nested arbitrarily deep — e.g. ``tracing`` ->
    ``logfire`` -> ``enable``/``disable`` is 3 levels).
    """
    paths: set[tuple[str, ...]] = set()
    for command in app.registered_commands:
        name = command.name
        if name is None and command.callback is not None:
            name = command.callback.__name__.replace("_", "-")
        assert name, f"unnamed command under {prefix}"
        paths.add((*prefix, name))
    for group in app.registered_groups:
        assert group.name, f"unnamed group under {prefix}"
        assert group.typer_instance is not None, f"group {group.name!r} has no typer_instance"
        paths |= _walk_typer_commands(group.typer_instance, (*prefix, group.name))
    return paths


_PLACEHOLDER = re.compile(r"^<[^>]+>$")
_BRACKET = re.compile(r"^\[[^\]]+\]$")
_INVOCATION = re.compile(r"`(mergecraft [^`]+)`")
_CLI_HEADING = "## \U0001f9f0 CLI"


def _parse_cli_invocation(invocation: str) -> list[tuple[str, ...]]:
    """Parse one backtick-quoted ``mergecraft ...`` string into command-path tuples.

    Honours the README's `` / `` shorthand for sibling subcommands (e.g.
    ``models list / set / show`` -> ``("models","list")``, ``("models","set")``,
    ``("models","show")``) and strips a single trailing positional-argument or
    option-flag token (``<placeholder>``, ``[placeholder]``, a bare upper-case
    value placeholder like ``N``, or a ``--flag``). This is a literal parse of
    what the row actually says — it does not infer a "corrected" form, which is
    exactly why ``mergecraft traces <run-id>`` parses to ``("traces",)`` (not a
    real leaf command; the real leaf is ``("traces","show")``) while
    ``mergecraft auth <provider>`` parses to ``("auth",)`` — also not a leaf,
    since ``auth`` only has named-provider children.
    """
    text = invocation.strip()
    if not text.startswith("mergecraft"):
        return []
    text = text[len("mergecraft") :].strip()
    if not text:
        return []
    branches = [branch.strip() for branch in text.split(" / ")]
    first_tokens = branches[0].split()
    group = first_tokens[0] if first_tokens else ""
    paths: list[tuple[str, ...]] = []
    for index, branch in enumerate(branches):
        tokens = branch.split()
        if index > 0 and tokens and tokens[0] != group:
            tokens = [group, *tokens]
        while tokens and (
            _PLACEHOLDER.match(tokens[-1]) or _BRACKET.match(tokens[-1]) or tokens[-1].isupper()
        ):
            tokens.pop()
        while tokens and tokens[-1].startswith("--"):
            tokens.pop()
        if tokens:
            paths.append(tuple(tokens))
    return paths


def _readme_cli_section() -> str:
    text = README.read_text(encoding="utf-8")
    start = text.index(_CLI_HEADING)
    rest = text[start + len(_CLI_HEADING) :]
    end_match = re.search(r"\n## ", rest)
    return rest[: end_match.start()] if end_match else rest


def _readme_documented_cli_paths() -> set[tuple[str, ...]]:
    documented: set[tuple[str, ...]] = set()
    for match in _INVOCATION.finditer(_readme_cli_section()):
        documented.update(_parse_cli_invocation(match.group(1)))
    return documented


def _auth_registry_providers() -> set[str]:
    providers: set[str] = set()
    for command in auth_app.registered_commands:
        assert command.name, "unnamed command under auth"
        providers.add(command.name)
    return providers


def _readme_auth_providers() -> set[str]:
    """Return the provider names README documents for ``mergecraft auth``.

    Handles today's shorthand row (``mergecraft auth <provider>`` followed by a
    parenthetical comma list) and, as a fallback, a future table shape where the
    reference-doc generator expands each provider into its own
    ``mergecraft auth <name>`` row instead of the shorthand.
    """
    text = README.read_text(encoding="utf-8")
    row_match = re.search(r"^\|\s*`mergecraft auth <provider>`.*$", text, re.MULTILINE)
    if row_match:
        paren_match = re.search(r"\(([^)]*)\)", row_match.group(0))
        assert paren_match, (
            f"README auth row has no parenthetical provider list: {row_match.group(0)!r}"
        )
        return {name.strip().strip("`") for name in paren_match.group(1).split(",") if name.strip()}
    documented_paths = _readme_documented_cli_paths()
    return {path[1] for path in documented_paths if len(path) >= 2 and path[0] == "auth"}


# ---------------------------------------------------------------------------
# generator-script loader (scripts/gen_reference_docs.py does not exist until G2.2)
# ---------------------------------------------------------------------------


def _load_gen_reference_docs() -> Any:
    """Load ``scripts/gen_reference_docs.py`` per-test (never at module import time).

    A missing script must fail exactly the tests that need it, not blow up
    collection for the whole file — mirrors ``tests/ci/test_hook_pins.py`` and
    ``tests/ci/test_action_yml_hygiene.py``.
    """
    path = REPO_ROOT / "scripts" / "gen_reference_docs.py"
    assert path.is_file(), "scripts/gen_reference_docs.py missing (lands in G2.2)"
    spec = importlib.util.spec_from_file_location("gen_reference_docs", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# Design note: no pre-existing sentinel convention exists anywhere in this repo
# (confirmed via grep) — these markers are this generator's own contract, first
# defined here; G2.2 must match them exactly.
_SCRATCH_ACTION_YML = """\
inputs:
  prompt:
    description: "Prompt text"
    required: false
  model_pin:
    description: "Pin the model"
    required: false
    default: "disabled"
outputs:
  result:
    description: "Result output"
    value: ${{ steps.run.outputs.result }}
"""

_SCRATCH_README = """\
# Scratch

## \U0001f9f0 CLI

<!-- BEGIN:cli-commands -->
<!-- END:cli-commands -->

#### Action inputs (`with:`)

<!-- BEGIN:action-inputs -->
<!-- END:action-inputs -->
"""


def _write_scratch_repo(tmp_path: Path, module: Any) -> tuple[Path, Path]:
    """Point the loaded module's path-level constants at a scratch copy.

    Only ``action.yml``/``README.md`` are scratch files — the CLI table half
    of the generator imports the real ``mergecraft.cli.app`` object (there is
    no file to substitute for a live Python object; the generator will import
    the real app in production too).
    """
    action_yml = tmp_path / "action.yml"
    readme = tmp_path / "README.md"
    action_yml.write_text(_SCRATCH_ACTION_YML, encoding="utf-8")
    readme.write_text(_SCRATCH_README, encoding="utf-8")
    module.ACTION_YML_PATH = action_yml
    module.README_PATH = readme
    return action_yml, readme


# ---------------------------------------------------------------------------
# 1. action inputs
# ---------------------------------------------------------------------------


def test_every_action_input_is_documented() -> None:
    real = set(_action_inputs())
    documented = set(_readme_action_input_table())
    assert documented == real, (
        f"README action-input table drift — missing: {sorted(real - documented)}, "
        f"stale/extra: {sorted(documented - real)}"
    )


# ---------------------------------------------------------------------------
# 2. action outputs
# ---------------------------------------------------------------------------


def test_both_action_outputs_are_documented() -> None:
    outputs = set(_action_outputs())
    assert outputs, "action.yml declares no outputs — nothing to check against"
    text = README.read_text(encoding="utf-8")
    missing = sorted(name for name in outputs if f"`{name}`" not in text)
    assert not missing, f"action.yml outputs undocumented anywhere in README.md: {missing}"


# ---------------------------------------------------------------------------
# 3. action input defaults
# ---------------------------------------------------------------------------


def test_action_input_defaults_match_yaml() -> None:
    inputs = _action_inputs()
    documented = _readme_action_input_table()
    mismatches: list[str] = []
    for name, spec in inputs.items():
        if "default" not in spec:
            # No default key at all in action.yml — distinct from an explicit
            # empty-string default; nothing to compare here.
            continue
        if name not in documented:
            # Presence is test_every_action_input_is_documented's job.
            continue
        real_default = str(spec["default"])
        doc_cell = documented[name]
        normalized = doc_cell.strip("`")
        if normalized in {"_(empty)_", "_(unset)_"}:
            normalized = ""
        if real_default != normalized:
            mismatches.append(
                f"{name}: action.yml default={real_default!r}, README says {doc_cell!r}"
            )
    assert not mismatches, "\n".join(mismatches)


# ---------------------------------------------------------------------------
# 4/5. CLI commands vs. README's CLI table (both directions)
# ---------------------------------------------------------------------------


def test_every_cli_command_is_documented() -> None:
    real = _walk_typer_commands(root_app)
    documented = _readme_documented_cli_paths()
    missing = sorted(real - documented)
    assert not missing, f"CLI commands missing from README's CLI table: {missing}"


def test_documented_cli_commands_all_exist() -> None:
    real = _walk_typer_commands(root_app)
    documented = _readme_documented_cli_paths()
    bogus = sorted(documented - real)
    assert not bogus, (
        f"README documents CLI invocations that don't resolve to a real registered "
        f"command: {bogus} (e.g. `mergecraft traces <run-id>` parses to ('traces',), "
        f"but the real leaf command is ('traces','show'))"
    )


# ---------------------------------------------------------------------------
# 6. auth provider list
# ---------------------------------------------------------------------------


def test_auth_provider_list_matches_registry() -> None:
    real = _auth_registry_providers()
    documented = _readme_auth_providers()
    assert documented == real, (
        f"README auth provider list drift — missing: {sorted(real - documented)}, "
        f"stale: {sorted(documented - real)}"
    )


# ---------------------------------------------------------------------------
# 7/8. scripts/gen_reference_docs.py --check behaviour (RED until G2.2)
# ---------------------------------------------------------------------------


def test_generator_check_mode_is_idempotent(tmp_path: Path) -> None:
    module = _load_gen_reference_docs()
    _write_scratch_repo(tmp_path, module)

    write_exit = module.main([])
    assert write_exit == 0, "default (write) mode must exit 0"

    check_exit = module.main(["--check"])
    assert check_exit == 0, "--check must exit 0 immediately after a write pass (idempotent)"


def test_generator_check_mode_detects_drift(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    module = _load_gen_reference_docs()
    _, readme = _write_scratch_repo(tmp_path, module)
    assert module.main([]) == 0

    generated = readme.read_text(encoding="utf-8")
    mutated = generated.replace(
        "<!-- END:action-inputs -->",
        "| `bogus_input` | `nope` | drift injected by test_generator_check_mode_detects_drift |\n"
        "<!-- END:action-inputs -->",
    )
    assert mutated != generated, "fixture sentinel marker not found; cannot inject drift"
    readme.write_text(mutated, encoding="utf-8")

    capsys.readouterr()  # drain any output from the write pass above
    check_exit = module.main(["--check"])
    captured = capsys.readouterr()
    output = captured.out + captured.err

    assert check_exit != 0, "--check must exit non-zero when README drifts from action.yml"
    diff_lines = [line for line in output.splitlines() if line.startswith(("---", "+++", "@@"))]
    assert diff_lines, (
        "--check must emit a unified diff (lines starting with ---/+++/@@) on drift, "
        f"not just a terse message; got:\n{output}"
    )
