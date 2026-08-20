"""Batch X (#337) RED catalog pins for new-manifest tools (minus C# / F-tier)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests.analyzers.support import FIXTURES_DIR, INLINE_BUDGET, import_module

BATCH_X_FIXTURES = FIXTURES_DIR / "batch-x"
_CATALOG_DIR = Path(__file__).resolve().parents[2] / "src" / "mergecraft" / "analyzers" / "catalog"
_PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"

# #337 proposed additions minus Roslyn/C# (D9). cargo-audit and cargo-deny are
# both named in issue §6 (vuln vs license); pin both ids, green after W5.
W4_IDS: tuple[str, ...] = ("tsc", "bandit", "jscpd")
W5_IDS: tuple[str, ...] = ("govulncheck", "cargo-audit", "cargo-deny", "typos")
W6_IDS: tuple[str, ...] = ("knip", "vulture")
NEW_MANIFEST_IDS: tuple[str, ...] = W4_IDS + W5_IDS + W6_IDS

_TOOL_WAVE: dict[str, str] = {
    "tsc": "W4",
    "bandit": "W4",
    "jscpd": "W4",
    "govulncheck": "W5",
    "cargo-audit": "W5",
    "cargo-deny": "W5",
    "typos": "W5",
    "knip": "W6",
    "vulture": "W6",
}

_EXPECTED_CATEGORY: dict[str, str] = {
    "tsc": "lint",
    "bandit": "security",
    "jscpd": "quality",
    "govulncheck": "vuln",
    "cargo-audit": "vuln",
    "cargo-deny": "license",
    "typos": "lint",
    "knip": "quality",
    "vulture": "quality",
}

# W3.1 language markers. A missing detect glob fails before the matching impl wave.
_DETECT_PATHS: tuple[tuple[str, str], ...] = (
    ("tsc", "tsconfig.json"),
    ("tsc", "src/index.ts"),
    ("tsc", "src/index.tsx"),
    ("bandit", "hello.py"),
    ("jscpd", "src/clone-a.js"),
    ("jscpd", "src/index.ts"),
    ("jscpd", "hello.py"),
    ("govulncheck", "go.mod"),
    ("govulncheck", "hello.go"),
    ("cargo-audit", "Cargo.toml"),
    ("cargo-audit", "Cargo.lock"),
    ("cargo-deny", "Cargo.toml"),
    ("cargo-deny", "Cargo.lock"),
    ("cargo-deny", "deny.toml"),
    ("typos", "hello.py"),
    ("typos", "README.md"),
    ("knip", "package.json"),
    ("knip", "src/index.ts"),
    ("knip", "src/index.js"),
    ("vulture", "hello.py"),
)

_AUTO_DETECT_CASES: tuple[tuple[str, Path, list[str]], ...] = (
    ("tsc", BATCH_X_FIXTURES / "tsc", ["src/index.ts", "tsconfig.json"]),
    ("bandit", BATCH_X_FIXTURES / "bandit", ["hello.py"]),
    ("jscpd", BATCH_X_FIXTURES / "jscpd", ["src/clone-a.js"]),
    ("govulncheck", BATCH_X_FIXTURES / "govulncheck", ["hello.go", "go.mod"]),
    ("cargo-audit", BATCH_X_FIXTURES / "cargo-audit", ["Cargo.lock", "Cargo.toml"]),
    ("cargo-deny", BATCH_X_FIXTURES / "cargo-deny", ["Cargo.toml", "deny.toml"]),
    ("typos", BATCH_X_FIXTURES / "typos", ["hello.py", "README.md"]),
    ("knip", BATCH_X_FIXTURES / "knip", ["package.json", "src/index.ts"]),
    ("vulture", BATCH_X_FIXTURES / "vulture", ["hello.py"]),
)

# D9 + #337 second-tier: do not add these in Batch X.
_DEFERRED_IDS: tuple[str, ...] = (
    "roslyn",
    "roslyn-analyzers",
    "csharp",
    "c-sharp",
    "dotnet-format",
    "dotnet_format",
    "credo",
    "dart-analyze",
    "dart_analyze",
    "scalafix",
    "shfmt",
    "nbqa",
    "lizard",
    "atlas",
)

_BANDIT_PIN_RE = re.compile(r"bandit\[toml\]==([0-9][0-9.]*)")


def _registry():
    return import_module("mergecraft.analyzers.registry")


def _wave_xfail(tool_id: str) -> pytest.MarkDecorator:
    wave = _TOOL_WAVE[tool_id]
    return pytest.mark.xfail(
        reason=f"green after {wave}: {tool_id} catalog manifest (#337)",
        strict=False,
    )


def _id_params(ids: tuple[str, ...]) -> list[pytest.ParameterSet]:
    return [pytest.param(tool_id, id=tool_id, marks=_wave_xfail(tool_id)) for tool_id in ids]


def _detect_params() -> list[pytest.ParameterSet]:
    return [
        pytest.param(
            tool_id,
            changed,
            id=f"{tool_id}-{changed}",
            marks=_wave_xfail(tool_id),
        )
        for tool_id, changed in _DETECT_PATHS
    ]


def _auto_params() -> list[pytest.ParameterSet]:
    return [
        pytest.param(
            tool_id,
            repo,
            changed,
            id=tool_id,
            marks=_wave_xfail(tool_id),
        )
        for tool_id, repo, changed in _AUTO_DETECT_CASES
    ]


def _enabled_ids(repo_root: Path, changed_files: list[str]) -> set[str]:
    return {
        manifest.id
        for manifest in _registry().detect_enabled(
            repo_root=repo_root,
            changed_files=changed_files,
            settings_overrides={},
        )
    }


def _make_security_bandit_pin() -> str:
    match = _BANDIT_PIN_RE.search(_PYPROJECT.read_text(encoding="utf-8"))
    assert match is not None, "pyproject.toml must pin bandit[toml] for make security"
    return match.group(1)


def _finding(*, tool: str, path: str, line: int):
    finding_mod = import_module("mergecraft.analyzers.finding")
    return finding_mod.make_finding(
        tool=tool,
        rule_id="clone",
        category="Maintainability & Code Quality",
        severity="Minor",
        confidence="likely",
        message=f"{tool} finding",
        path=path,
        start_line=line,
        end_line=line,
        source="analyzer",
    )


# --- already green: fixtures + D9 absence ---------------------------------


@pytest.mark.parametrize("tool_id", NEW_MANIFEST_IDS)
def test_batch_x_detect_fixture_skeleton_exists(tool_id: str) -> None:
    repo = BATCH_X_FIXTURES / tool_id
    assert repo.is_dir(), f"missing Batch X fixture repo: {repo}"
    assert any(repo.rglob("*")), f"Batch X fixture repo is empty: {repo}"


@pytest.mark.parametrize("tool_id", NEW_MANIFEST_IDS)
def test_batch_x_catalog_check_parser_skeleton_exists(tool_id: str) -> None:
    sarif = FIXTURES_DIR / "sarif" / f"{tool_id}-minimal.sarif.json"
    native_json = FIXTURES_DIR / "native" / f"{tool_id}-minimal.json"
    native_jsonl = FIXTURES_DIR / "native" / f"{tool_id}-minimal.jsonl"
    assert sarif.is_file() or native_json.is_file() or native_jsonl.is_file(), (
        f"{tool_id} needs a catalog-check parser skeleton under fixtures/sarif or fixtures/native"
    )


def test_make_security_bandit_pin_is_present() -> None:
    assert _make_security_bandit_pin()


@pytest.mark.parametrize("tool_id", _DEFERRED_IDS)
def test_deferred_tools_are_not_in_catalog(tool_id: str) -> None:
    ids = _registry().known_analyzer_ids()
    assert tool_id not in ids
    assert not (_CATALOG_DIR / f"{tool_id}.yaml").is_file(), (
        f"D9/#337: do not add {tool_id}.yaml in Batch X"
    )


def test_empty_changed_files_do_not_enable_new_manifests() -> None:
    ids = _enabled_ids(BATCH_X_FIXTURES / "tsc", [])
    assert ids.isdisjoint(NEW_MANIFEST_IDS)


@pytest.mark.parametrize("tool_id", NEW_MANIFEST_IDS)
def test_unrelated_readme_does_not_match_before_manifest(tool_id: str) -> None:
    if tool_id in {"typos", "jscpd"}:
        pytest.skip("typos/jscpd may detect prose or many-language paths")
    ids = _enabled_ids(BATCH_X_FIXTURES / tool_id, ["README.md"])
    assert tool_id not in ids


# --- xfail until W4 / W5 / W6 ---------------------------------------------


@pytest.mark.parametrize("tool_id", _id_params(NEW_MANIFEST_IDS))
def test_new_manifest_catalog_yaml_exists(tool_id: str) -> None:
    path = _CATALOG_DIR / f"{tool_id}.yaml"
    assert path.is_file(), f"{tool_id} catalog YAML missing at {path}"


@pytest.mark.parametrize("tool_id", _id_params(NEW_MANIFEST_IDS))
def test_new_manifest_is_importable(tool_id: str) -> None:
    manifest = _registry().get_manifest(tool_id)
    assert manifest.id == tool_id


@pytest.mark.parametrize("tool_id", _id_params(NEW_MANIFEST_IDS))
def test_new_manifest_default_enabled_auto(tool_id: str) -> None:
    manifest = _registry().get_manifest(tool_id)
    assert manifest.default_enabled == "auto"


@pytest.mark.parametrize("tool_id", _id_params(NEW_MANIFEST_IDS))
def test_new_manifest_category(tool_id: str) -> None:
    manifest = _registry().get_manifest(tool_id)
    assert manifest.category == _EXPECTED_CATEGORY[tool_id]


@pytest.mark.parametrize("tool_id", _id_params(NEW_MANIFEST_IDS))
def test_new_manifest_declares_timeout(tool_id: str) -> None:
    manifest = _registry().get_manifest(tool_id)
    assert manifest.timeout_s > 0


@pytest.mark.parametrize("tool_id", _id_params(NEW_MANIFEST_IDS))
def test_new_manifest_has_catalog_check_parser_fixture(tool_id: str) -> None:
    docs = import_module("mergecraft.analyzers.catalog_docs")
    manifest = _registry().get_manifest(tool_id)
    assert docs.manifest_has_fixture(manifest, fixture_root=FIXTURES_DIR), (
        f"{tool_id} must keep a catalog-check-shaped parser fixture (D15)"
    )


@pytest.mark.parametrize(("tool_id", "changed"), _detect_params())
def test_new_manifest_detect_globs(tool_id: str, changed: str) -> None:
    registry = _registry()
    manifest = registry.get_manifest(tool_id)
    matched = registry.filter_changed_files_for_manifest(manifest, [changed])
    assert matched == [changed], (
        f"{tool_id} detect.files must match {changed!r}; got {matched!r} "
        f"from {list(manifest.detect.files)!r}"
    )


@pytest.mark.parametrize(("tool_id", "repo", "changed"), _auto_params())
def test_new_manifest_auto_enables_on_detect_markers(
    tool_id: str, repo: Path, changed: list[str]
) -> None:
    assert repo.is_dir(), f"missing Batch X fixture repo: {repo}"
    assert tool_id in _enabled_ids(repo, changed)


@pytest.mark.xfail(reason="green after W4: tsc --noEmit whole-program catalog (#337)", strict=False)
def test_tsc_command_is_no_emit_whole_program() -> None:
    manifest = _registry().get_manifest("tsc")
    assert "--noEmit" in manifest.command
    assert manifest.scope == "repo"
    assert manifest.category == "lint"


@pytest.mark.xfail(reason="green after W4: bandit reuses make security pin (#337)", strict=False)
def test_bandit_version_reuses_make_security_pin() -> None:
    manifest = _registry().get_manifest("bandit")
    assert manifest.version == _make_security_bandit_pin()
    assert manifest.command[0] == "bandit"
    assert manifest.category == "security"


@pytest.mark.xfail(
    reason="green after W4: jscpd scope repo + diff-line attribution (D14)", strict=False
)
def test_jscpd_scope_is_repo() -> None:
    manifest = _registry().get_manifest("jscpd")
    assert manifest.scope == "repo"
    assert manifest.category == "quality"


@pytest.mark.xfail(
    reason="green after W4: jscpd scope repo + diff-line attribution (D14)", strict=False
)
def test_jscpd_drops_preexisting_clones_off_the_diff() -> None:
    """D14: duplication is repo-wide, but findings must sit on diff lines only."""
    scope = import_module("mergecraft.analyzers.scope")
    manifest = _registry().get_manifest("jscpd")
    assert manifest.scope == "repo"
    diff = """diff --git a/src/clone-a.js b/src/clone-a.js
@@ -1,3 +1,4 @@
 function greet(name) {
   return "hello " + name;
 }
+// touched
"""
    on_diff = _finding(tool="jscpd", path="src/clone-a.js", line=4)
    preexisting = _finding(tool="jscpd", path="src/clone-b.js", line=1)
    kept = scope.filter_to_diff([on_diff, preexisting], diff_text=diff)
    assert kept == [on_diff]


@pytest.mark.xfail(reason="green after W4: tsc whole-program + diff-filter (#337)", strict=False)
def test_tsc_diff_filter_keeps_only_changed_lines() -> None:
    scope = import_module("mergecraft.analyzers.scope")
    manifest = _registry().get_manifest("tsc")
    assert manifest.scope == "repo"
    diff = """diff --git a/src/index.ts b/src/index.ts
@@ -1,2 +1,3 @@
 export const n = 1;
+export const added = 2;
"""
    on_diff = _finding(tool="tsc", path="src/index.ts", line=2)
    preexisting = _finding(tool="tsc", path="src/untouched.ts", line=1)
    kept = scope.filter_to_diff([on_diff, preexisting], diff_text=diff)
    assert kept == [on_diff]


@pytest.mark.xfail(
    reason="green after W5: cargo-audit vs cargo-deny are distinct ids (#337)", strict=False
)
def test_cargo_audit_and_deny_are_distinct_catalog_ids() -> None:
    registry = _registry()
    audit = registry.get_manifest("cargo-audit")
    deny = registry.get_manifest("cargo-deny")
    assert audit.id != deny.id
    assert audit.category == "vuln"
    assert deny.category == "license"
    assert "audit" in " ".join(audit.command)
    assert "deny" in " ".join(deny.command)


@pytest.mark.parametrize("tool_id", _id_params(NEW_MANIFEST_IDS))
def test_new_manifest_reports_unavailable_when_toolchain_absent(
    tool_id: str, tmp_path: Path
) -> None:
    resolve = import_module("mergecraft.analyzers.resolve")
    run = import_module("mergecraft.analyzers.run")
    manifest = _registry().get_manifest(tool_id)
    plan = resolve.resolve_analyzer(
        manifest=manifest,
        repo_root=tmp_path,
        repo_has_tool=False,
        ci_artifact_available=False,
        managed_available=False,
        container_available=False,
        allow_repo_binaries=False,
    )
    assert plan.mode == "skip"
    assert plan.reason
    outcome = run.run_plan(plan)
    assert outcome.status == "unavailable"


def test_new_manifest_findings_honor_inline_budget() -> None:
    budget = import_module("mergecraft.analyzers.budget")
    findings = [
        _finding(tool=tool_id, path=f"src/{tool_id}-{index}.ext", line=index)
        for tool_id in NEW_MANIFEST_IDS
        for index in range(1, 4)
    ]
    placement = budget.place_findings(findings, inline_budget=INLINE_BUDGET)
    assert len(placement.inline) <= INLINE_BUDGET
    assert placement.mechanical_section is not None
