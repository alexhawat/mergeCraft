"""G2 + RD1.1 — generated CLI/Action reference docs vs. live ``action.yml``/CLI app.

G2 pinned README sentinel tables; RD1.1 retargets the contract to
``docs/action-reference.md`` and ``docs/cli.md`` and asserts the landing README
no longer owns the full generated tables. RD1.2 implements the generator move;
this suite stays RED (xfail) until then.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
import yaml

from mergecraft.cli.app import app as root_app
from mergecraft.cli.auth_cmd import app as auth_app
from tests.ci.workflow_support import REPO_ROOT
from tests.docs.support import load_script_module

if TYPE_CHECKING:
    import typer

ACTION_YML = REPO_ROOT / "action.yml"
README = REPO_ROOT / "README.md"
ACTION_REFERENCE_DOC = REPO_ROOT / "docs" / "action-reference.md"
CLI_DOC = REPO_ROOT / "docs" / "cli.md"

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


def _action_reference_input_table() -> dict[str, str]:
    """Parse ``docs/action-reference.md`` action-input table.

    Returns ``{input_name: raw_default_cell_text}``.
    """
    assert ACTION_REFERENCE_DOC.is_file(), (
        f"missing {ACTION_REFERENCE_DOC.relative_to(REPO_ROOT)} (RD1.2)"
    )
    text = ACTION_REFERENCE_DOC.read_text(encoding="utf-8")
    match = re.search(r"The full input list:\n\n(\|.*\n(?:\|.*\n)+)", text)
    assert match, (
        f"{ACTION_REFERENCE_DOC.name}: could not locate 'The full input list:' action-input table"
    )
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
    """Recursively collect every leaf command's full path from a Typer app."""
    paths: set[tuple[str, ...]] = set()
    for command in app.registered_commands:
        if command.hidden:
            continue
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
_CLI_SENTINEL_BEGIN = "<!-- BEGIN:cli-commands -->"


def _parse_cli_invocation(invocation: str) -> list[tuple[str, ...]]:
    """Parse one backtick-quoted ``mergecraft ...`` string into command-path tuples."""
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


def _cli_doc_text() -> str:
    assert CLI_DOC.is_file(), f"missing {CLI_DOC.relative_to(REPO_ROOT)} (RD1.2)"
    text = CLI_DOC.read_text(encoding="utf-8")
    begin = text.find(_CLI_SENTINEL_BEGIN)
    if begin == -1:
        return text
    rest = text[begin + len(_CLI_SENTINEL_BEGIN) :]
    end = rest.find("<!-- END:cli-commands -->")
    return rest[:end] if end != -1 else rest


def _cli_doc_documented_cli_paths() -> set[tuple[str, ...]]:
    documented: set[tuple[str, ...]] = set()
    for match in _INVOCATION.finditer(_cli_doc_text()):
        documented.update(_parse_cli_invocation(match.group(1)))
    return documented


def _auth_registry_providers() -> set[str]:
    providers: set[str] = set()
    for command in auth_app.registered_commands:
        assert command.name, "unnamed command under auth"
        providers.add(command.name)
    return providers


def _cli_doc_auth_providers() -> set[str]:
    """Return provider names documented for ``mergecraft auth`` in ``docs/cli.md``."""
    text = _cli_doc_text()
    row_match = re.search(r"^\|\s*`mergecraft auth <provider>`.*$", text, re.MULTILINE)
    if row_match:
        paren_match = re.search(r"\(([^)]*)\)", row_match.group(0))
        assert paren_match, (
            f"CLI doc auth row has no parenthetical provider list: {row_match.group(0)!r}"
        )
        return {name.strip().strip("`") for name in paren_match.group(1).split(",") if name.strip()}
    documented_paths = _cli_doc_documented_cli_paths()
    return {path[1] for path in documented_paths if len(path) >= 2 and path[0] == "auth"}


# ---------------------------------------------------------------------------
# generator-script loader
# ---------------------------------------------------------------------------


def _load_gen_reference_docs() -> Any:
    """Load ``scripts/gen_reference_docs.py`` per-test (never at module import time)."""
    return load_script_module(REPO_ROOT / "scripts" / "gen_reference_docs.py")


def _patch_module_doc_paths(module: Any, *, cli_doc: Path, action_doc: Path) -> None:
    module.CLI_DOC_PATH = cli_doc
    module.ACTION_DOC_PATH = action_doc


def _generator_splices_doc_paths() -> bool:
    """True once RD1.2 retargets the generator off ``README.md`` sentinels."""
    source = (REPO_ROOT / "scripts" / "gen_reference_docs.py").read_text(encoding="utf-8")
    return "CLI_DOC_PATH" in source and "ACTION_DOC_PATH" in source


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

See [CLI reference](docs/cli.md) and [Action reference](docs/action-reference.md).
"""

_SCRATCH_CLI_DOC = """\
# CLI reference

<!-- BEGIN:cli-commands -->
<!-- END:cli-commands -->
"""

_SCRATCH_ACTION_REF = """\
# Action reference

#### Action inputs (`with:`)

<!-- BEGIN:action-inputs -->
<!-- END:action-inputs -->

#### Action outputs

<!-- BEGIN:action-outputs -->
<!-- END:action-outputs -->
"""


def _write_scratch_repo(tmp_path: Path, module: Any) -> dict[str, Path]:
    """Point the loaded module's path constants at scratch copies."""
    action_yml = tmp_path / "action.yml"
    readme = tmp_path / "README.md"
    cli_doc = tmp_path / "docs" / "cli.md"
    action_doc = tmp_path / "docs" / "action-reference.md"
    cli_doc.parent.mkdir(parents=True, exist_ok=True)

    action_yml.write_text(_SCRATCH_ACTION_YML, encoding="utf-8")
    readme.write_text(_SCRATCH_README, encoding="utf-8")
    cli_doc.write_text(_SCRATCH_CLI_DOC, encoding="utf-8")
    action_doc.write_text(_SCRATCH_ACTION_REF, encoding="utf-8")

    module.ACTION_YML_PATH = action_yml
    module.README_PATH = readme
    _patch_module_doc_paths(module, cli_doc=cli_doc, action_doc=action_doc)
    return {
        "action_yml": action_yml,
        "readme": readme,
        "cli_doc": cli_doc,
        "action_doc": action_doc,
    }


# ---------------------------------------------------------------------------
# RD1.1 — generated reference pages live off the landing README
# ---------------------------------------------------------------------------


def test_action_inputs_table_lives_in_action_reference_doc() -> None:
    real = set(_action_inputs())
    documented = set(_action_reference_input_table())
    assert documented == real, (
        f"{ACTION_REFERENCE_DOC.name} action-input table drift — missing: "
        f"{sorted(real - documented)}, stale/extra: {sorted(documented - real)}"
    )
    readme_text = README.read_text(encoding="utf-8")
    assert "The full input list:" not in readme_text, (
        "README.md must not host the full action-input table after RD1.2"
    )


def test_action_outputs_table_lives_in_action_reference_doc() -> None:
    outputs = set(_action_outputs())
    assert outputs, "action.yml declares no outputs — nothing to check against"
    assert ACTION_REFERENCE_DOC.is_file(), (
        f"missing {ACTION_REFERENCE_DOC.relative_to(REPO_ROOT)} (RD1.2)"
    )
    action_text = ACTION_REFERENCE_DOC.read_text(encoding="utf-8")
    missing = sorted(name for name in outputs if f"`{name}`" not in action_text)
    assert not missing, f"action.yml outputs undocumented in {ACTION_REFERENCE_DOC.name}: {missing}"
    readme_text = README.read_text(encoding="utf-8")
    assert "<!-- BEGIN:action-outputs -->" not in readme_text, (
        "README.md must not host generated action-output sentinels after RD1.2"
    )


def test_cli_table_lives_in_cli_doc() -> None:
    real = _walk_typer_commands(root_app)
    documented = _cli_doc_documented_cli_paths()
    missing = sorted(real - documented)
    assert not missing, f"CLI commands missing from {CLI_DOC.name}: {missing}"
    readme_text = README.read_text(encoding="utf-8")
    assert _CLI_SENTINEL_BEGIN not in readme_text, (
        "README.md must not contain BEGIN:cli-commands after RD1.2"
    )


def test_generator_check_fails_on_cli_doc_drift(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    module = _load_gen_reference_docs()
    paths = _write_scratch_repo(tmp_path, module)
    assert module.main([]) == 0

    cli_doc = paths["cli_doc"]
    generated = cli_doc.read_text(encoding="utf-8")
    mutated = generated.replace(
        "<!-- END:cli-commands -->",
        "| `mergecraft bogus` | drift injected by test_generator_check_fails_on_cli_doc_drift |\n"
        "<!-- END:cli-commands -->",
    )
    assert mutated != generated, "fixture CLI sentinel marker not found; cannot inject drift"
    cli_doc.write_text(mutated, encoding="utf-8")

    capsys.readouterr()
    check_exit = module.main(["--check"])
    captured = capsys.readouterr()
    output = captured.out + captured.err

    assert check_exit != 0, "--check must exit non-zero when docs/cli.md drifts"
    diff_lines = [line for line in output.splitlines() if line.startswith(("---", "+++", "@@"))]
    assert diff_lines, "--check must emit a unified diff on CLI doc drift; got:\n" + output


def test_generator_check_fails_on_action_doc_drift(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    module = _load_gen_reference_docs()
    paths = _write_scratch_repo(tmp_path, module)
    assert module.main([]) == 0

    action_doc = paths["action_doc"]
    generated = action_doc.read_text(encoding="utf-8")
    mutated = generated.replace(
        "<!-- END:action-inputs -->",
        "| `bogus_input` | `nope` | drift injected by test_generator_check_fails_on_action_doc_drift |\n"
        "<!-- END:action-inputs -->",
    )
    assert mutated != generated, (
        "fixture action-input sentinel marker not found; cannot inject drift"
    )
    action_doc.write_text(mutated, encoding="utf-8")

    capsys.readouterr()
    check_exit = module.main(["--check"])
    captured = capsys.readouterr()
    output = captured.out + captured.err

    assert check_exit != 0, "--check must exit non-zero when docs/action-reference.md drifts"
    diff_lines = [line for line in output.splitlines() if line.startswith(("---", "+++", "@@"))]
    assert diff_lines, (
        "--check must emit a unified diff on action-reference doc drift; got:\n" + output
    )


def test_readme_links_to_generated_reference_pages() -> None:
    readme_text = README.read_text(encoding="utf-8")
    assert "docs/cli.md" in readme_text, "README.md must link to docs/cli.md"
    assert "docs/action-reference.md" in readme_text, (
        "README.md must link to docs/action-reference.md"
    )


# ---------------------------------------------------------------------------
# G2 carry-over — same contracts, retargeted off README (RED until RD1.2)
# ---------------------------------------------------------------------------


def test_every_action_input_is_documented() -> None:
    real = set(_action_inputs())
    documented = set(_action_reference_input_table())
    assert documented == real, (
        f"action-reference action-input table drift — missing: {sorted(real - documented)}, "
        f"stale/extra: {sorted(documented - real)}"
    )


def test_both_action_outputs_are_documented() -> None:
    outputs = set(_action_outputs())
    assert outputs, "action.yml declares no outputs — nothing to check against"
    assert ACTION_REFERENCE_DOC.is_file(), (
        f"missing {ACTION_REFERENCE_DOC.relative_to(REPO_ROOT)} (RD1.2)"
    )
    text = ACTION_REFERENCE_DOC.read_text(encoding="utf-8")
    missing = sorted(name for name in outputs if f"`{name}`" not in text)
    assert not missing, f"action.yml outputs undocumented in {ACTION_REFERENCE_DOC.name}: {missing}"


def test_action_input_defaults_match_yaml() -> None:
    inputs = _action_inputs()
    documented = _action_reference_input_table()
    mismatches: list[str] = []
    for name, spec in inputs.items():
        if "default" not in spec:
            continue
        if name not in documented:
            continue
        real_default = str(spec["default"])
        doc_cell = documented[name]
        normalized = doc_cell.strip("`")
        if normalized in {"_(empty)_", "_(unset)_"}:
            normalized = ""
        if real_default != normalized:
            mismatches.append(f"{name}: action.yml default={real_default!r}, doc says {doc_cell!r}")
    assert not mismatches, "\n".join(mismatches)


def test_every_cli_command_is_documented() -> None:
    real = _walk_typer_commands(root_app)
    documented = _cli_doc_documented_cli_paths()
    missing = sorted(real - documented)
    assert not missing, f"CLI commands missing from {CLI_DOC.name}: {missing}"


def test_documented_cli_commands_all_exist() -> None:
    real = _walk_typer_commands(root_app)
    documented = _cli_doc_documented_cli_paths()
    bogus = sorted(documented - real)
    assert not bogus, (
        f"{CLI_DOC.name} documents CLI invocations that don't resolve to a real registered "
        f"command: {bogus}"
    )


def test_auth_provider_list_matches_registry() -> None:
    real = _auth_registry_providers()
    documented = _cli_doc_auth_providers()
    assert documented == real, (
        f"CLI doc auth provider list drift — missing: {sorted(real - documented)}, "
        f"stale: {sorted(documented - real)}"
    )


# ---------------------------------------------------------------------------
# G2 generator --check behaviour (retargeted scratch docs; RED until RD1.2)
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
    paths = _write_scratch_repo(tmp_path, module)
    assert module.main([]) == 0

    action_doc = paths["action_doc"]
    generated = action_doc.read_text(encoding="utf-8")
    mutated = generated.replace(
        "<!-- END:action-inputs -->",
        "| `bogus_input` | `nope` | drift injected by test_generator_check_mode_detects_drift |\n"
        "<!-- END:action-inputs -->",
    )
    assert mutated != generated, (
        "fixture action-input sentinel marker not found; cannot inject drift"
    )
    action_doc.write_text(mutated, encoding="utf-8")

    capsys.readouterr()
    check_exit = module.main(["--check"])
    captured = capsys.readouterr()
    output = captured.out + captured.err

    assert check_exit != 0, "--check must exit non-zero when generated docs drift"
    diff_lines = [line for line in output.splitlines() if line.startswith(("---", "+++", "@@"))]
    assert diff_lines, (
        "--check must emit a unified diff on drift, not just a terse message; got:\n" + output
    )


def test_generator_fails_when_a_sentinel_pair_is_removed(tmp_path: Path) -> None:
    assert _generator_splices_doc_paths(), (
        "gen_reference_docs.py must splice docs/action-reference.md (RD1.2)"
    )
    module = _load_gen_reference_docs()
    paths = _write_scratch_repo(tmp_path, module)
    action_doc = paths["action_doc"]

    text = action_doc.read_text(encoding="utf-8")
    assert "<!-- BEGIN:action-outputs -->" in text
    stripped = text.replace("<!-- BEGIN:action-outputs -->\n<!-- END:action-outputs -->\n", "", 1)
    assert stripped != text, "fixture action-output sentinel pair not found; cannot remove it"
    action_doc.write_text(stripped, encoding="utf-8")

    with pytest.raises(SystemExit):
        module.main([])
    with pytest.raises(SystemExit):
        module.main(["--check"])
