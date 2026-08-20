"""``mergecraft policy`` — lint, test, and explain policy-as-code rules (DG5)."""

from __future__ import annotations

from pathlib import Path
from typing import NoReturn

import typer
import yaml

from mergecraft.cli.consoles import err_console as console
from mergecraft.cli.exits import (
    CLI_CONFIGURATION_EXIT_CODE,
)
from mergecraft.policy.exceptions import PolicyException, parse_exceptions_document
from mergecraft.policy.schema import PolicyConfigError, PolicyRule, parse_rules_document
from mergecraft.policy.scoping import ScopeContext, resolve_effective_rules

app = typer.Typer(
    name="policy",
    help="Lint, test, and explain versioned policy-as-code rules.",
    no_args_is_help=True,
)


def _bail(msg: str) -> NoReturn:
    console.print(f"[red]{msg}[/red]")
    raise typer.Exit(CLI_CONFIGURATION_EXIT_CODE)


def _policy_dir(repo: Path) -> Path:
    return repo / ".mergecraft" / "policy"


def _load_policy_rules(repo: Path) -> list[PolicyRule]:
    rules_path = _policy_dir(repo) / "rules.yaml"
    if not rules_path.is_file():
        _bail(f"policy rules file not found: {rules_path}")
    try:
        return parse_rules_document(rules_path.read_text(encoding="utf-8"))
    except PolicyConfigError as exc:
        _bail(str(exc))


def _load_policy_exceptions(repo: Path) -> list[PolicyException]:
    exceptions_path = _policy_dir(repo) / "exceptions.yaml"
    if not exceptions_path.is_file():
        return []
    try:
        return parse_exceptions_document(exceptions_path.read_text(encoding="utf-8"))
    except PolicyConfigError as exc:
        _bail(str(exc))


@app.command("lint")
def lint_cmd(
    repo: Path = typer.Option(
        Path("."),
        "--repo",
        "-r",
        help="Repository root containing ``.mergecraft/policy/``.",
        exists=True,
        file_okay=False,
        dir_okay=True,
    ),
) -> None:
    """Validate policy rule YAML under ``.mergecraft/policy/``."""
    repo_root = repo.resolve()
    rules = _load_policy_rules(repo_root)
    exceptions = _load_policy_exceptions(repo_root)
    parts = [f"{len(rules)} rule(s)"]
    if exceptions:
        parts.append(f"{len(exceptions)} exception(s)")
    console.print(f"[green]policy lint passed[/green] ({', '.join(parts)})")


def _fixture_expects_no_match(fixture_name: str) -> bool:
    """Return whether a fixture asserts no effective rules match its path."""
    return "should-not" in fixture_name


@app.command("test")
def run_fixtures_cmd(
    fixtures: Path = typer.Option(
        ...,
        "--fixtures",
        help="Directory of should-trigger / should-not fixture YAML files.",
        exists=True,
        file_okay=False,
        dir_okay=True,
    ),
    repo: Path = typer.Option(
        Path("."),
        "--repo",
        "-r",
        help="Repository root containing ``.mergecraft/policy/``.",
        exists=True,
        file_okay=False,
        dir_okay=True,
    ),
) -> None:
    """Run should-trigger and should-not policy fixtures.

    Fixture contract (filename-driven):

    - ``*should-not*``: ``path`` must match **no** effective rules.
    - All other fixtures: ``path`` must match **at least one** effective rule.

    The optional ``violation`` field is documentary only; matching is by scope.
    """
    repo_root = repo.resolve()
    rules = _load_policy_rules(repo_root)
    fixture_paths = sorted(fixtures.glob("*.yaml"))
    if not fixture_paths:
        _bail(f"no fixture YAML files found in {fixtures}")

    failures: list[str] = []
    for fixture_path in fixture_paths:
        raw = yaml.safe_load(fixture_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            failures.append(f"{fixture_path.name}: fixture must be a mapping")
            continue
        fixture_path_value = str(raw.get("path", ""))
        context = ScopeContext(
            org="",
            repo="",
            branch="",
            path=fixture_path_value,
            language="",
        )
        effective = resolve_effective_rules(rules, context=context)
        matched = [entry.rule.id for entry in effective]
        name = fixture_path.stem
        expect_no_match = _fixture_expects_no_match(name)
        if expect_no_match:
            if matched:
                failures.append(
                    f"{name}: expected no effective rules for path "
                    f"{fixture_path_value!r}, matched {', '.join(matched)}"
                )
            else:
                console.print(f"[green]{name}: pass[/green] (no effective rules)")
        elif not matched:
            failures.append(
                f"{name}: expected at least one effective rule for path {fixture_path_value!r}"
            )
        else:
            console.print(f"[green]{name}: pass[/green] (matched {', '.join(matched)})")

    if failures:
        for failure in failures:
            console.print(f"[red]{failure}[/red]")
        raise typer.Exit(CLI_CONFIGURATION_EXIT_CODE)


@app.command("explain")
def explain_cmd(
    path: str = typer.Option(..., "--path", help="File path to explain effective rules for."),
    org: str = typer.Option("", "--org", help="Organization slug for scope resolution."),
    repo: str = typer.Option("", "--repo", help="Repository name for scope resolution."),
    branch: str = typer.Option("main", "--branch", help="Branch name for scope resolution."),
    language: str = typer.Option("", "--language", help="Language id for scope resolution."),
    cwd: Path = typer.Option(
        Path("."),
        "--cwd",
        help="Repository root containing ``.mergecraft/policy/``.",
        exists=True,
        file_okay=False,
        dir_okay=True,
    ),
) -> None:
    """List effective rules for a path and name each rule's source layer."""
    repo_root = cwd.resolve()
    rules = _load_policy_rules(repo_root)
    context = ScopeContext(
        org=org,
        repo=repo,
        branch=branch,
        path=path,
        language=language,
    )
    effective = resolve_effective_rules(rules, context=context)
    if not effective:
        console.print("(no effective rules)")
        return
    for entry in effective:
        console.print(
            f"- {entry.rule.id} "
            f"(source layer: {entry.source_layer}, enforcement: {entry.rule.enforcement})"
        )


__all__ = ["app"]
