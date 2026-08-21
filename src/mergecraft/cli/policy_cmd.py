"""``mergecraft policy`` — lint, test, explain, effective, and simulate (DG5, #358)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import typer
import yaml

from mergecraft.cli.consoles import err_console as console
from mergecraft.cli.errors import cli_bail
from mergecraft.cli.exits import (
    CLI_CONFIGURATION_EXIT_CODE,
)
from mergecraft.policy.exceptions import PolicyException, parse_exceptions_document
from mergecraft.policy.lifecycle import simulate_rule
from mergecraft.policy.packs import load_shipped_pack_rules
from mergecraft.policy.schema import PolicyConfigError, PolicyRule, parse_rule, parse_rules_document
from mergecraft.policy.scoping import EffectiveRule, ScopeContext, resolve_effective_rules

app = typer.Typer(
    name="policy",
    help="Lint, test, explain, and simulate versioned policy-as-code rules.",
    no_args_is_help=True,
)


def _policy_dir(repo: Path) -> Path:
    return repo / ".mergecraft" / "policy"


def _load_policy_rules(repo: Path) -> list[PolicyRule]:
    rules_path = _policy_dir(repo) / "rules.yaml"
    if not rules_path.is_file():
        return load_shipped_pack_rules()
    try:
        return parse_rules_document(rules_path.read_text(encoding="utf-8"))
    except PolicyConfigError as exc:
        cli_bail(str(exc))


def _load_policy_exceptions(repo: Path) -> list[PolicyException]:
    exceptions_path = _policy_dir(repo) / "exceptions.yaml"
    if not exceptions_path.is_file():
        return []
    try:
        return parse_exceptions_document(exceptions_path.read_text(encoding="utf-8"))
    except PolicyConfigError as exc:
        cli_bail(str(exc))


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
        cli_bail(f"no fixture YAML files found in {fixtures}")

    failures: list[str] = []
    for fixture_path in fixture_paths:
        raw = yaml.safe_load(fixture_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            failures.append(f"{fixture_path.name}: fixture must be a mapping")
            continue
        fixture_path_value = str(raw.get("path", ""))
        fixture_symbol = raw.get("symbol")
        context = ScopeContext(
            org="",
            repo="",
            branch="",
            path=fixture_path_value,
            language="",
            symbol=str(fixture_symbol) if fixture_symbol else None,
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
    symbol: str | None = typer.Option(
        None,
        "--symbol",
        help="Optional symbol name so symbol-scoped rules can match.",
    ),
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
        symbol=symbol,
    )
    _print_effective(resolve_effective_rules(rules, context=context))


@app.command("effective")
def effective_cmd(
    path: str = typer.Option(
        ".", "--path", help="File path to resolve the effective rule set for."
    ),
    org: str = typer.Option("", "--org", help="Organization slug for scope resolution."),
    repo: str = typer.Option("", "--repo", help="Repository name for scope resolution."),
    branch: str = typer.Option("main", "--branch", help="Branch name for scope resolution."),
    language: str = typer.Option("", "--language", help="Language id for scope resolution."),
    symbol: str | None = typer.Option(
        None,
        "--symbol",
        help="Optional symbol name so the source of every effective rule can include symbol scope.",
    ),
    cwd: Path = typer.Option(
        Path("."),
        "--cwd",
        help="Repository root containing ``.mergecraft/policy/``.",
        exists=True,
        file_okay=False,
        dir_okay=True,
    ),
) -> None:
    """Show the effective policy set and the source of every rule."""
    repo_root = cwd.resolve()
    rules = _load_policy_rules(repo_root)
    context = ScopeContext(
        org=org,
        repo=repo,
        branch=branch,
        path=path,
        language=language,
        symbol=symbol,
    )
    _print_effective(resolve_effective_rules(rules, context=context))


@app.command("simulate")
def simulate_cmd(
    rule: Path = typer.Option(
        ...,
        "--rule",
        help="Proposed rule YAML to simulate against past PRs before enabling it.",
        exists=True,
        file_okay=True,
        dir_okay=False,
    ),
    past_prs: Path = typer.Option(
        ...,
        "--past-prs",
        help="YAML or JSON list of past PRs (number, paths, optional would_trigger).",
        exists=True,
        file_okay=True,
        dir_okay=False,
    ),
) -> None:
    """Simulate a proposed rule against past PRs."""
    try:
        proposed = parse_rule(rule.read_text(encoding="utf-8"))
    except PolicyConfigError as exc:
        cli_bail(str(exc))
    loaded = yaml.safe_load(past_prs.read_text(encoding="utf-8"))
    if not isinstance(loaded, list):
        cli_bail("past PRs document must be a list")
    past: list[dict[str, Any]] = [item for item in loaded if isinstance(item, dict)]
    report = simulate_rule(rule=proposed, past_prs=past)
    if not report.triggered:
        console.print("(no past PRs would trigger)")
        return
    console.print(f"simulate triggered on {len(report.triggered)} past PR(s):")
    for number in report.triggered:
        console.print(f"- #{number}")


def _print_effective(effective: list[EffectiveRule]) -> None:
    if not effective:
        console.print("(no effective rules)")
        return
    for entry in effective:
        console.print(
            f"- {entry.rule.id} "
            f"(source layer: {entry.source_layer}, enforcement: {entry.rule.enforcement})"
        )


__all__ = ["app"]
