"""``self-silencing`` — added suppressions and loosened analyzer config are made visible (#942)."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from textwrap import dedent
from typing import Any

import pytest

_GIT = ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", "-c", "commit.gpgsign=false"]


# The developer's real ~/.gitconfig can be enormous; fixtures never read it.
_GIT_ENV = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        [*_GIT, "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        env=_GIT_ENV,
    )
    return result.stdout


def _commit_change(
    tmp_path: Path, files_before: dict[str, str], files_after: dict[str, str]
) -> tuple[Path, str]:
    """Return ``(repo, unified_diff)`` for a base commit followed by a head commit."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    for rel, text in files_before.items():
        target = repo / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base", "--allow-empty")
    base = _git(repo, "rev-parse", "HEAD").strip()
    for rel, text in files_after.items():
        target = repo / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "head")
    return repo, _git(repo, "diff", base, "HEAD")


def _scan(repo: Path, diff: str, *, tier: str = "trusted") -> list[Any]:
    from mergecraft.analyzers.self_silencing import scan_diff

    result = scan_diff(repo_root=repo, diff_text=diff, tier=tier)  # type: ignore[arg-type]
    return list(result.findings)


# --------------------------------------------------------------------------- markers


@pytest.mark.parametrize(
    ("path", "line", "marker", "codes", "severity"),
    [
        ("app.py", "run(cmd)  # nosec B603", "nosec", ["B603"], "Major"),
        ("app.py", "import os  # noqa: E501, F401", "noqa", ["E501", "F401"], "Minor"),
        ("app.py", "x = f()  # type: ignore[arg-type]", "type: ignore", ["arg-type"], "Minor"),
        (
            "app.py",
            "x = f()  # pylint: disable=unused-import",
            "pylint: disable",
            ["unused-import"],
            "Minor",
        ),
        (
            "web.ts",
            "// eslint-disable-next-line no-eval",
            "eslint-disable-next-line",
            ["no-eval"],
            "Minor",
        ),
        ("web.ts", "// @ts-ignore", "@ts-ignore", [], "Minor"),
        ("web.ts", "// @ts-expect-error", "@ts-expect-error", [], "Minor"),
        ("lib.rs", "#[allow(clippy::unwrap_used)]", "allow", ["clippy::unwrap_used"], "Minor"),
        ("main.go", "x := run() //nolint:gosec", "nolint", ["gosec"], "Major"),
        ("core.cpp", "int x = f(); // NOLINT(bugprone-foo)", "NOLINT", ["bugprone-foo"], "Minor"),
        (
            "lib.rb",
            "eval(x) # rubocop:disable Security/Eval",
            "rubocop:disable",
            ["Security/Eval"],
            "Major",
        ),
        ("Svc.java", '@SuppressWarnings("unchecked")', "SuppressWarnings", ["unchecked"], "Minor"),
        ("run.sh", "# shellcheck disable=SC2086", "shellcheck disable", ["SC2086"], "Minor"),
        ("app.py", "token = 'x'  # gitleaks:allow", "gitleaks:allow", [], "Major"),
        (
            "docs/TRACING.md",
            "<!-- trufflehog:ignore -->",
            "trufflehog:ignore",
            [],
            "Major",
        ),
        ("app.py", "token = 'x'  # trufflehog:ignore", "trufflehog:ignore", [], "Major"),
        (
            "app.py",
            "q = build(sql)  # nosemgrep: python.lang.security.audit",
            "nosemgrep",
            [],
            "Major",
        ),
    ],
)
def test_each_added_marker_produces_a_finding_naming_marker_codes_and_severity(
    tmp_path: Path, path: str, line: str, marker: str, codes: list[str], severity: str
) -> None:
    repo, diff = _commit_change(tmp_path, {path: "x = 1\n"}, {path: f"x = 1\n{line}\n"})

    findings = _scan(repo, diff)

    assert len(findings) == 1
    finding = findings[0]
    assert finding.tool == "self-silencing"
    assert finding.path == path
    assert finding.start_line == 2
    assert finding.severity == severity
    assert finding.source == "analyzer"
    assert marker.casefold() in finding.message.casefold()
    for code in codes:
        assert code in finding.message
    assert "justify in the PR or remove" in finding.message


def test_untrusted_tier_bumps_severity_one_level(tmp_path: Path) -> None:
    repo, diff = _commit_change(
        tmp_path, {"a.py": "x = 1\n"}, {"a.py": "x = 1\nimport os  # noqa: F401\nrun()  # nosec\n"}
    )

    trusted = {f.start_line: f.severity for f in _scan(repo, diff, tier="trusted")}
    untrusted = {f.start_line: f.severity for f in _scan(repo, diff, tier="untrusted")}

    assert trusted == {2: "Minor", 3: "Major"}
    assert untrusted == {2: "Major", 3: "Critical"}


def test_markers_already_on_base_are_not_reported(tmp_path: Path) -> None:
    before = "import os  # noqa: F401\nvalue = compute()\n"
    after = "import os  # noqa: F401\nvalue = compute(1)\nmore = 2\n"
    repo, diff = _commit_change(tmp_path, {"a.py": before}, {"a.py": after})

    assert _scan(repo, diff) == []


def test_editing_a_line_that_keeps_its_existing_marker_is_not_a_new_suppression(
    tmp_path: Path,
) -> None:
    before = "import os, sys  # noqa: F401\n"
    after = "import os, sys, json  # noqa: F401\n"
    repo, diff = _commit_change(tmp_path, {"a.py": before}, {"a.py": after})

    assert _scan(repo, diff) == []


def test_changing_the_silenced_rule_codes_is_reported(tmp_path: Path) -> None:
    before = "import os  # noqa: F401\n"
    after = "import os  # noqa: F401, E501, S101\n"
    repo, diff = _commit_change(tmp_path, {"a.py": before}, {"a.py": after})

    findings = _scan(repo, diff)

    assert len(findings) == 1
    assert "E501" in findings[0].message


def test_removed_lines_and_prose_files_never_produce_findings(tmp_path: Path) -> None:
    repo, diff = _commit_change(
        tmp_path,
        {"a.py": "x = 1  # nosec\n", "NOTES.md": "x\n"},
        {"a.py": "x = 1\n", "NOTES.md": "Use `# noqa: E501` sparingly; avoid `// @ts-ignore`.\n"},
    )

    assert _scan(repo, diff) == []


def test_a_secret_scanner_marker_already_on_base_is_not_reported(tmp_path: Path) -> None:
    before = "token = 'x'  # trufflehog:ignore\n"
    after = "token = 'x'  # trufflehog:ignore\nmore = 2\n"
    repo, diff = _commit_change(tmp_path, {"a.py": before}, {"a.py": after})

    assert _scan(repo, diff) == []


def test_code_only_markers_in_prose_are_prose_but_scanner_markers_are_not(tmp_path: Path) -> None:
    """A secret scanner honours its marker in any file; `# noqa` in a document is prose."""
    repo, diff = _commit_change(
        tmp_path,
        {"NOTES.md": "x\n"},
        {
            "NOTES.md": (
                "Use `# noqa: E501` sparingly; avoid `// @ts-ignore`.\n<!-- trufflehog:ignore -->\n"
            )
        },
    )

    findings = _scan(repo, diff)

    assert [f.start_line for f in findings] == [2]
    assert "trufflehog:ignore" in findings[0].message


# --------------------------------------------------------------------------- config edits


def test_disabling_an_analyzer_in_mergecraft_config_is_a_major_finding(tmp_path: Path) -> None:
    before = "analyzers:\n  enabled: true\n"
    after = dedent(
        """\
        analyzers:
          enabled: true
          overrides:
            gitleaks:
              enabled: false
        """
    )
    repo, diff = _commit_change(
        tmp_path, {".mergecraft/config.yaml": before}, {".mergecraft/config.yaml": after}
    )

    findings = _scan(repo, diff)

    assert len(findings) == 1
    assert findings[0].severity == "Major"
    assert findings[0].path == ".mergecraft/config.yaml"
    assert "gitleaks" in findings[0].message
    assert "justify in the PR or remove" in findings[0].message


def test_disabling_every_analyzer_is_reported(tmp_path: Path) -> None:
    repo, diff = _commit_change(
        tmp_path,
        {".mergecraft/config.yaml": "analyzers:\n  enabled: true\n"},
        {".mergecraft/config.yaml": "analyzers:\n  enabled: false\n"},
    )

    findings = _scan(repo, diff)

    assert [finding.severity for finding in findings] == ["Major"]


@pytest.mark.parametrize(
    "spelling",
    ["0", '"false"', "no", "off"],
    ids=["int-zero", "quoted-false", "no", "off"],
)
def test_a_disabling_edit_in_another_yaml_spelling_is_reported(
    tmp_path: Path, spelling: str
) -> None:
    """The settings model reads these as ``False``, so the detector has to as well."""
    repo, diff = _commit_change(
        tmp_path,
        {".mergecraft/config.yaml": "analyzers:\n  enabled: true\n"},
        {".mergecraft/config.yaml": f"analyzers:\n  enabled: {spelling}\n"},
    )

    findings = _scan(repo, diff)

    assert [finding.severity for finding in findings] == ["Major"]


def test_an_already_disabled_analyzer_stays_unreported_in_another_spelling(
    tmp_path: Path,
) -> None:
    """`enabled: 0 -> 'false'` is not a new loosening, so it is not reported."""
    repo, diff = _commit_change(
        tmp_path,
        {".mergecraft/config.yaml": "analyzers:\n  enabled: 0\n"},
        {".mergecraft/config.yaml": 'analyzers:\n  enabled: "false"\n'},
    )

    assert _scan(repo, diff) == []


def test_widening_antislop_ignore_and_lowering_the_inline_budget_are_reported(
    tmp_path: Path,
) -> None:
    before = dedent(
        """\
        analyzers:
          inlineBudget: 8
          overrides:
            antislop:
              ignore: ["tests/**"]
        """
    )
    after = dedent(
        """\
        analyzers:
          inlineBudget: 2
          overrides:
            antislop:
              ignore: ["tests/**", "src/**"]
        """
    )
    repo, diff = _commit_change(
        tmp_path, {".mergecraft/config.yaml": before}, {".mergecraft/config.yaml": after}
    )

    messages = " ".join(finding.message for finding in _scan(repo, diff))

    assert "src/**" in messages
    assert "inlineBudget" in messages


def test_pure_tightening_of_mergecraft_config_is_not_reported_as_loosening(tmp_path: Path) -> None:
    before = dedent(
        """\
        analyzers:
          inlineBudget: 2
          overrides:
            gitleaks:
              enabled: false
            antislop:
              ignore: ["tests/**", "src/**"]
        """
    )
    after = dedent(
        """\
        analyzers:
          inlineBudget: 12
          overrides:
            gitleaks:
              enabled: true
            antislop:
              ignore: ["tests/**"]
        """
    )
    repo, diff = _commit_change(
        tmp_path, {".mergecraft/config.yaml": before}, {".mergecraft/config.yaml": after}
    )

    assert all(finding.severity in {"Trivial"} for finding in _scan(repo, diff))


def test_ruff_ignore_and_excluded_paths_are_reported_with_the_specific_change(
    tmp_path: Path,
) -> None:
    before = 'line-length = 100\n[lint]\nselect = ["E", "F", "S"]\nignore = []\n'
    after = (
        'line-length = 100\nextend-exclude = ["legacy"]\n'
        '[lint]\nselect = ["E", "F"]\nignore = ["E501"]\n'
    )
    repo, diff = _commit_change(tmp_path, {"ruff.toml": before}, {"ruff.toml": after})

    findings = _scan(repo, diff)
    messages = " ".join(finding.message for finding in findings)

    assert "E501" in messages
    assert "legacy" in messages
    assert "S" in messages  # the dropped security rule family
    assert all(finding.path == "ruff.toml" for finding in findings)
    assert any(finding.severity == "Major" for finding in findings)  # S (bandit) family removed


def test_pyproject_tool_ruff_loosening_is_reported(tmp_path: Path) -> None:
    before = '[project]\nname = "x"\n[tool.ruff.lint]\nselect = ["E"]\n'
    after = '[project]\nname = "x"\n[tool.ruff.lint]\nselect = ["E"]\nignore = ["F401"]\n'
    repo, diff = _commit_change(tmp_path, {"pyproject.toml": before}, {"pyproject.toml": after})

    findings = _scan(repo, diff)

    assert len(findings) == 1
    assert "F401" in findings[0].message
    assert findings[0].path == "pyproject.toml"


def test_unrelated_pyproject_edits_are_not_reported(tmp_path: Path) -> None:
    before = '[project]\nname = "x"\nversion = "1"\n'
    after = '[project]\nname = "x"\nversion = "2"\n'
    repo, diff = _commit_change(tmp_path, {"pyproject.toml": before}, {"pyproject.toml": after})

    assert _scan(repo, diff) == []


def test_eslint_json_rule_turned_off_and_ignored_paths_are_reported(tmp_path: Path) -> None:
    before = '{"rules": {"no-eval": "error"}, "ignorePatterns": []}\n'
    after = '{"rules": {"no-eval": "off"}, "ignorePatterns": ["dist/**", "src/legacy/**"]}\n'
    repo, diff = _commit_change(tmp_path, {".eslintrc.json": before}, {".eslintrc.json": after})

    messages = " ".join(finding.message for finding in _scan(repo, diff))

    assert "no-eval" in messages
    assert "src/legacy/**" in messages


def test_eslint_yaml_rule_set_to_zero_is_reported(tmp_path: Path) -> None:
    before = "rules:\n  eqeqeq: error\n"
    after = "rules:\n  eqeqeq: 0\n"
    repo, diff = _commit_change(tmp_path, {".eslintrc.yml": before}, {".eslintrc.yml": after})

    findings = _scan(repo, diff)

    assert len(findings) == 1
    assert "eqeqeq" in findings[0].message


def test_new_ignore_file_entries_are_loosening_for_security_scanners(tmp_path: Path) -> None:
    repo, diff = _commit_change(
        tmp_path,
        {".gitleaksignore": "# none\n"},
        {".gitleaksignore": "# none\nabc123:src/a.py:1\n"},
    )

    findings = _scan(repo, diff)

    assert len(findings) == 1
    assert findings[0].severity == "Major"
    assert findings[0].path == ".gitleaksignore"


def test_config_files_are_read_through_confinement_never_followed_out_of_the_repo(
    tmp_path: Path,
) -> None:
    repo, _diff = _commit_change(tmp_path, {"README.md": "x\n"}, {"README.md": "y\n"})
    outside = tmp_path / "outside.toml"
    outside.write_text('[lint]\nignore = ["E501"]\n', encoding="utf-8")
    (repo / "ruff.toml").symlink_to(outside)
    synthetic = (
        "diff --git a/ruff.toml b/ruff.toml\nnew file mode 120000\n"
        "--- /dev/null\n+++ b/ruff.toml\n@@ -0,0 +1 @@\n+../outside.toml\n"
    )

    findings = _scan(repo, synthetic)

    assert all("E501" not in finding.message for finding in findings)


# --------------------------------------------------------------------------- eligibility


def test_self_silencing_is_an_in_process_analyzer_eligible_on_every_tier() -> None:
    from mergecraft.analyzers.registry import get_manifest
    from mergecraft.analyzers.trust import (
        IN_PROCESS_ANALYZER_IDS,
        evaluate_manifest_for_shell,
        evaluate_manifest_for_tier,
    )

    manifest = get_manifest("self-silencing")
    assert "self-silencing" in IN_PROCESS_ANALYZER_IDS
    assert evaluate_manifest_for_shell(manifest=manifest, shell="disabled").skipped is False
    assert (
        evaluate_manifest_for_tier(manifest=manifest, tier="untrusted", cause="fork").skipped
        is False
    )


def test_adapter_runs_it_and_skips_with_a_named_reason_without_a_diff(tmp_path: Path) -> None:
    from mergecraft.analyzers.adapters import run_adapter

    repo, diff = _commit_change(tmp_path, {"a.py": "x = 1\n"}, {"a.py": "x = 1\nrun()  # nosec\n"})

    ran = run_adapter(
        tool_id="self-silencing", repo_root=repo, changed_files=["a.py"], diff_text=diff
    )
    assert [finding.rule_id for finding in ran.findings]
    assert ran.skipped is False

    skipped = run_adapter(tool_id="self-silencing", repo_root=repo, changed_files=["a.py"])
    assert skipped.skipped is True
    assert skipped.skip_reason
    assert "self-silencing" in skipped.skip_reason


def test_minimal_fixture_diff_yields_its_documented_finding(tmp_path: Path) -> None:
    import yaml

    from tests.analyzers.support import FIXTURES_DIR

    fixture = yaml.safe_load(
        (FIXTURES_DIR / "self-silencing" / "self-silencing-minimal.yaml").read_text(
            encoding="utf-8"
        )
    )

    findings = _scan(tmp_path, fixture["diff"])

    assert [(f.rule_id, f.severity) for f in findings] == [
        (fixture["rule_id"], fixture["severity"])
    ]


# --------------------------------------------------------------------------- review fixes

_PAD = "".join(f"# filler {index}\n" for index in range(30))


def _scoped(repo: Path, diff: str) -> tuple[list[Any], list[Any]]:
    """Run the scan through the pipeline's scoping stage, as ``run_analyzer_pipeline`` does."""
    from mergecraft.analyzers.dispositions import DispositionLedger
    from mergecraft.analyzers.scope import scope_findings

    raw = _scan(repo, diff)
    ledger = DispositionLedger()
    ledger.register_raw(raw)
    kept = scope_findings(raw, diff_text=diff, repo_root=repo, ledger=ledger)
    return kept, ledger.entries()


@pytest.mark.parametrize(
    ("path", "before", "after"),
    [
        (
            ".mergecraft/config.yaml",
            f"version: 1\n{_PAD}analyzers:\n  enabled: true\n",
            f"version: 1\n{_PAD}analyzers:\n  enabled: false\n",
        ),
        (
            "ruff.toml",
            f"line-length = 100\n{_PAD}[lint]\nignore = []\n",
            f'line-length = 100\n{_PAD}[lint]\nignore = ["S101"]\n',
        ),
        (
            "ruff.toml",
            f'line-length = 100\n{_PAD}[lint]\nselect = ["E", "S"]\n',
            f'line-length = 100\n{_PAD}[lint]\nselect = ["E"]\n',
        ),
    ],
    ids=["mergecraft-enabled-false", "ruff-ignore-gained", "ruff-select-dropped"],
)
def test_config_loosening_far_from_line_one_survives_diff_scoping(
    tmp_path: Path, path: str, before: str, after: str
) -> None:
    """A structured change anchors inside its hunk, so scoping cannot drop it (#942)."""
    repo, diff = _commit_change(tmp_path, {path: before}, {path: after})

    kept, entries = _scoped(repo, diff)

    assert [finding.rule_id for finding in kept] == ["config-loosened"]
    assert kept[0].start_line is not None
    assert kept[0].start_line > 30
    assert all(entry.disposition != "dropped:out_of_scope" for entry in entries)


def test_deleting_a_config_file_survives_diff_scoping(tmp_path: Path) -> None:
    repo, diff = _commit_change(
        tmp_path, {"ruff.toml": "line-length = 100\n", "keep.txt": "x\n"}, {"keep.txt": "y\n"}
    )
    (repo / "ruff.toml").unlink()
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "delete")
    diff = _git(repo, "diff", "HEAD~2", "HEAD")

    kept, _entries = _scoped(repo, diff)

    assert [(finding.path, finding.start_line) for finding in kept] == [("ruff.toml", None)]
    assert "deleted the config file" in kept[0].message


def test_removing_inline_budget_falls_back_to_the_default_and_is_reported(
    tmp_path: Path,
) -> None:
    """Dropping ``inlineBudget: 12`` lowers the budget to the settings default."""
    repo, diff = _commit_change(
        tmp_path,
        {".mergecraft/config.yaml": "analyzers:\n  inlineBudget: 12\n  enabled: true\n"},
        {".mergecraft/config.yaml": "analyzers:\n  enabled: true\n"},
    )

    messages = [finding.message for finding in _scan(repo, diff)]

    assert any("lowered inlineBudget 12 -> 8" in message for message in messages)


def test_moving_an_existing_marker_to_another_hunk_is_not_a_new_suppression(
    tmp_path: Path,
) -> None:
    body = "".join(f"x{index} = {index}\n" for index in range(40))
    marker = "import os  # noqa: F401\n"
    repo, diff = _commit_change(tmp_path, {"m.py": marker + body}, {"m.py": body + marker})

    assert diff.count("@@ -") == 2  # the move spans two hunks
    assert _scan(repo, diff) == []
