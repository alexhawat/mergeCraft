"""One repo-path glob dialect for policy scopes, ``ignorePaths`` and Scope paths (#1307).

Policy rule and waiver scopes, the review ignore matcher and the declared Scope
paths all read the same gitignore-style glob: ``*`` and ``?`` stay inside one
segment, ``**`` spans zero or more directories and a leading ``./`` is dropped.
The table below is run through all three call sites, so a pattern cannot mean
one thing in a blocking policy rule and another in ``review.ignorePaths``.
Organization and repository scopes compare case-insensitively, as GitHub does.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import yaml
from loguru import logger

from tests.support.policy_fixtures import exception, rule, write_policy

_NOW = datetime(2030, 1, 1, tzinfo=UTC)

# Each row is a glob, a repo path and whether the glob matches it.
_TABLE: list[tuple[str, str, bool]] = [
    ("**/migrations/**", "migrations/0001_init.py", True),
    ("**/migrations/**", "db/migrations/0001.py", True),
    ("services/payments/**/*.py", "services/payments/charge.py", True),
    ("services/payments/**/*.py", "services/payments/v2/charge.py", True),
    ("src/**/*.py", "src/x.py", True),
    ("src/*.py", "src/deep/x.py", False),
    ("src/*.py", "src/x.py", True),
    ("src/legacy*", "src/legacy_auth/x.py", False),
    ("src/legacy*", "src/legacy_auth", True),
    ("./src/*.py", "src/x.py", True),
    ("src/billing/**", "src/billing/a/b.py", True),
    ("README.md", "docs/README.md", False),
]
_TABLE_IDS = [
    "root-migrations",
    "nested-migrations",
    "double-star-zero-dirs",
    "double-star-one-dir",
    "src-double-star-root-file",
    "star-stays-in-segment",
    "star-same-segment",
    "prefix-star-not-a-directory",
    "prefix-star-same-segment",
    "leading-dot-slash",
    "trailing-double-star",
    "anchored-at-root",
]


def _policy_matches(tmp_path: Path, pattern: str, path: str) -> bool:
    """Whether the real review evaluator raises a row for a rule scoped to ``pattern``."""
    from mergecraft.policy.review import evaluate_review_policy, load_repo_policy

    write_policy(tmp_path, rules=[rule("policy.dialect", scope={"path": pattern})])
    rows = evaluate_review_policy(
        load_repo_policy(tmp_path),
        changed_paths=[path],
        org="acme",
        repo="demo",
        base_ref="main",
        exceptions_trusted=True,
        now=_NOW,
    )
    return any(str(row.rule_id) == "policy.dialect" for row in rows)


@pytest.mark.parametrize(("pattern", "path", "expected"), _TABLE, ids=_TABLE_IDS)
def test_policy_scope_reads_the_shared_glob_dialect(
    tmp_path: Path, pattern: str, path: str, expected: bool
) -> None:
    assert _policy_matches(tmp_path, pattern, path) is expected


@pytest.mark.parametrize(("pattern", "path", "expected"), _TABLE, ids=_TABLE_IDS)
def test_ignore_paths_reads_the_shared_glob_dialect(
    pattern: str, path: str, expected: bool
) -> None:
    from mergecraft.review_policy.ignore_paths import build_review_ignore, parse_ignore_paths

    ignore = build_review_ignore(input_value=None, review=None, source="test")
    patterns = parse_ignore_paths(pattern)
    custom = type(ignore)(patterns=tuple(patterns), generated_defaults=False, source="test")
    assert custom.is_ignored(path) is expected


@pytest.mark.parametrize(("pattern", "path", "expected"), _TABLE, ids=_TABLE_IDS)
def test_scope_paths_read_the_shared_glob_dialect(pattern: str, path: str, expected: bool) -> None:
    from mergecraft.classify.path_globs import path_full_matches_glob

    assert path_full_matches_glob(pattern, path) is expected


def test_bundled_migrations_pack_fires_on_a_root_migrations_directory(tmp_path: Path) -> None:
    """The shipped ``migrations.expand-contract`` rule covers the top-level layout."""
    from mergecraft.policy.review import evaluate_review_policy, load_repo_policy

    pack = Path(__file__).resolve().parents[2] / "src/mergecraft/policy/packs/migrations.yaml"
    rules = yaml.safe_load(pack.read_text(encoding="utf-8"))["rules"]
    write_policy(tmp_path, rules=rules)
    snapshot = load_repo_policy(tmp_path)

    for path in ("migrations/0001_init.py", "app/migrations/0002.py"):
        rows = evaluate_review_policy(
            snapshot,
            changed_paths=[path],
            org="acme",
            repo="demo",
            base_ref="main",
            exceptions_trusted=True,
            now=_NOW,
        )
        assert [str(row.rule_id) for row in rows] == ["migrations.expand-contract"], path


def test_a_prefix_waiver_does_not_cover_a_sibling_directory(tmp_path: Path) -> None:
    """A waiver scoped ``src/legacy*`` leaves ``src/legacy_auth/login.py`` unwaived."""
    from mergecraft.policy.review import evaluate_review_policy, load_repo_policy

    write_policy(
        tmp_path,
        rules=[rule("policy.legacy", scope={"path": "src/**"})],
        exceptions=[exception(rule_id="policy.legacy", path="src/legacy*")],
    )
    rows = evaluate_review_policy(
        load_repo_policy(tmp_path),
        changed_paths=["src/legacy_auth/login.py"],
        org="acme",
        repo="demo",
        base_ref="main",
        exceptions_trusted=True,
        now=_NOW,
    )
    assert [str(row.rule_id) for row in rows] == ["policy.legacy"]
    assert rows[0].severity == "Major"


@pytest.mark.parametrize(
    "scope",
    [{"org": "acme"}, {"org": "ACME", "repo": "demo"}, {"org": "Acme", "repo": "Demo"}],
    ids=["org-lower", "org-upper", "org-and-repo-mixed"],
)
def test_org_and_repo_scopes_compare_case_insensitively(
    tmp_path: Path, scope: dict[str, str]
) -> None:
    from mergecraft.policy.review import evaluate_review_policy, load_repo_policy

    write_policy(tmp_path, rules=[rule("policy.org", scope=scope)])
    rows = evaluate_review_policy(
        load_repo_policy(tmp_path),
        changed_paths=["src/app.py"],
        org="Acme",
        repo="DEMO",
        base_ref="main",
        exceptions_trusted=True,
        now=_NOW,
    )
    assert [str(row.rule_id) for row in rows] == ["policy.org"]


def test_a_rule_scoped_to_another_repository_is_logged(tmp_path: Path) -> None:
    """A rule whose org or repo can never match this repository says so in the run log."""
    from mergecraft.policy.review import evaluate_review_policy, load_repo_policy

    write_policy(
        tmp_path,
        rules=[rule("policy.elsewhere", scope={"org": "acme", "repo": "other"})],
    )
    messages: list[str] = []
    sink = logger.add(lambda message: messages.append(str(message)), level="WARNING")
    try:
        rows = evaluate_review_policy(
            load_repo_policy(tmp_path),
            changed_paths=["src/app.py"],
            org="acme",
            repo="demo",
            base_ref="main",
            exceptions_trusted=True,
            now=_NOW,
        )
    finally:
        logger.remove(sink)
    assert rows == []
    assert any("policy.elsewhere" in message for message in messages)


def test_rule_simulation_reads_the_shared_glob_dialect() -> None:
    from mergecraft.policy.lifecycle import simulate_rule

    payload: dict[str, Any] = {"id": "r", "scope": {"path": "**/migrations/**"}}
    report = simulate_rule(
        rule=payload,
        past_prs=[
            {"number": 1, "paths": ["migrations/0001.py"]},
            {"number": 2, "paths": ["src/app.py"]},
        ],
    )
    assert report.triggered == (1,)


def test_a_scope_that_matched_nested_paths_under_fnmatch_is_logged(tmp_path: Path) -> None:
    """``src/*`` no longer covers ``src/a/b.py``; the run log says so and names ``**``."""
    from mergecraft.policy.review import evaluate_review_policy, load_repo_policy

    write_policy(tmp_path, rules=[rule("policy.narrowed", scope={"path": "src/*"})])
    messages: list[str] = []
    sink = logger.add(lambda message: messages.append(str(message)), level="WARNING")
    try:
        rows = evaluate_review_policy(
            load_repo_policy(tmp_path),
            changed_paths=["src/a/b.py"],
            org="acme",
            repo="demo",
            base_ref="main",
            exceptions_trusted=True,
            now=_NOW,
        )
    finally:
        logger.remove(sink)
    assert rows == []
    assert any("policy.narrowed" in m and "src/a/b.py" in m and "**" in m for m in messages)
