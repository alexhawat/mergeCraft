"""C3 pattern scanners."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.analyzers.support import C3_PATTERN_TOOLS, import_module

PATTERN_EXCLUSIVE_GROUP = "pattern-scanner"


def _catalog_ids() -> set[str]:
    registry = import_module("mergecraft.analyzers.registry")
    return {manifest.id for manifest in registry.load_catalog()}


def _run(tool_id: str, repo_root: Path, changed_files: list[str]):
    adapters = import_module("mergecraft.analyzers.adapters")
    return adapters.run_adapter(
        tool_id=tool_id,
        repo_root=repo_root,
        changed_files=changed_files,
        tier="trusted",
    )


def test_repo_rules_preferred_and_named(adapter_fixture_repo: Path) -> None:
    pattern = import_module("mergecraft.analyzers.pattern")
    if "semgrep" not in _catalog_ids():
        pytest.fail("semgrep manifest missing from catalog")

    selection = pattern.resolve_pattern_backend(repo_root=adapter_fixture_repo)
    assert selection.ruleset_source in {"repo", "default"}, selection
    assert selection.ruleset_name, "review must name whose rules ran (C3.2)"


def test_exactly_one_pattern_backend_runs(adapter_fixture_repo: Path) -> None:
    registry = import_module("mergecraft.analyzers.registry")
    enabled = registry.select_enabled_analyzers(
        repo_root=adapter_fixture_repo,
        changed_files=["src/fixture_app/eval_sink.py"],
        settings=None,
    )
    pattern_backends = [
        m.id
        for m in enabled
        if m.exclusive_group == PATTERN_EXCLUSIVE_GROUP or m.id in C3_PATTERN_TOOLS
    ]
    assert len(pattern_backends) == 1, (
        f"exactly one pattern backend must run (D13/C1); got {pattern_backends!r}"
    )


@pytest.mark.parametrize("tool_id", list(C3_PATTERN_TOOLS))
def test_pattern_scanner_catches_planted_sink(tool_id: str, adapter_fixture_repo: Path) -> None:
    if tool_id not in _catalog_ids():
        pytest.fail(f"{tool_id} manifest missing from catalog")

    path, line = C3_PATTERN_TOOLS[tool_id]
    result = _run(tool_id, adapter_fixture_repo, [path])
    assert not result.skipped, result.skip_reason
    matches = [f for f in result.findings if f.path == path and f.start_line == line]
    assert matches, f"{tool_id} must catch taint-style sink at {path}:{line}"


def test_semgrep_default_ruleset_catches_action_yml_expression_footgun(
    adapter_fixture_repo: Path,
) -> None:
    """c498e82 regression: default semgrep ruleset flags ``${{`` inside ``description:``.

    ``tests/analyzers/fixtures/repo/action.yml`` plants the exact shape of
    the incident this guards against — a ``description:`` field embedding a
    literal ``${{ secrets.* }}`` example meant only as consumer-facing
    documentation. GitHub evaluates that expression lexically regardless of
    field semantics, which breaks the action's *load* step for every
    consumer. See ``docs/_standards/coding-standards.md`` and
    ``scripts/check_action_yml_hygiene.py`` for the other two layers of
    defense against this same class of bug.
    """
    if "semgrep" not in _catalog_ids():
        pytest.fail("semgrep manifest missing from catalog")

    result = _run("semgrep", adapter_fixture_repo, ["action.yml"])
    assert not result.skipped, result.skip_reason
    matches = [
        f
        for f in result.findings
        if f.path == "action.yml" and "action-yml-description-expression" in f.rule_id
    ]
    assert matches, (
        "default semgrep ruleset must flag the planted `${{` inside "
        f"action.yml's description: text; got {result.findings!r}"
    )


def test_taint_finding_requires_verification_before_review(adapter_fixture_repo: Path) -> None:
    pipeline = import_module("mergecraft.analyzers.pipeline")
    verifier = import_module("mergecraft.agents.verifier")

    if "semgrep" not in _catalog_ids():
        pytest.fail("semgrep manifest missing from catalog")

    path, _line = C3_PATTERN_TOOLS["semgrep"]
    raw = _run("semgrep", adapter_fixture_repo, [path])
    assert raw.findings

    taint_findings = [
        f
        for f in raw.findings
        if "taint" in f.message.casefold() or f.severity in {"Critical", "Major"}
    ]
    assert taint_findings, "fixture must produce a taint-class finding for D11 routing"

    published = pipeline.filter_for_review(
        findings=taint_findings,
        verified_ids=set(),
        require_verification=True,
    )
    assert not published, "taint findings must not reach review before verification (D11/C3.4)"

    finding = taint_findings[0]
    assert verifier.should_verify(finding) is True

    published_after = pipeline.filter_for_review(
        findings=taint_findings,
        verified_ids={finding.fingerprint},
        require_verification=True,
    )
    assert published_after, "verified taint finding may reach review"
