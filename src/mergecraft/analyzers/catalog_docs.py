"""Catalog documentation enforcement and ANALYZERS.md generation (C6)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

from mergecraft.analyzers.manifest import (
    AnalyzerManifest,
    ManifestValidationError,
    load_manifest_file,
    validate_manifest,
)
from mergecraft.analyzers.registry import load_catalog

if TYPE_CHECKING:
    from collections.abc import Iterable

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_FIXTURE_ROOT = _REPO_ROOT / "tests" / "analyzers" / "fixtures"
_DEFAULT_DOC_PATH = _REPO_ROOT / "docs" / "ANALYZERS.md"
_TABLE_ROW_RE = re.compile(r"^\|\s*`([^`]+)`\s*\|")


class CatalogIntegrityError(ValueError):
    """Raised when a manifest fails the ship gate (fixture, doc row, severity_map)."""


def parse_analyzers_doc(path: Path) -> set[str]:
    """Return analyzer ids declared in ``docs/ANALYZERS.md`` table rows."""
    if not path.is_file():
        return set()
    ids: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        match = _TABLE_ROW_RE.match(line.strip())
        if match is not None:
            ids.add(match.group(1))
    return ids


def _fixture_candidates(manifest_id: str) -> tuple[Path, ...]:
    return (
        _DEFAULT_FIXTURE_ROOT / "sarif" / f"{manifest_id}-minimal.sarif.json",
        _DEFAULT_FIXTURE_ROOT / "native" / f"{manifest_id}-minimal.json",
        _DEFAULT_FIXTURE_ROOT / "native" / f"{manifest_id}-minimal.jsonl",
        _DEFAULT_FIXTURE_ROOT / "native" / f"{manifest_id}-minimal.txt",
        _DEFAULT_FIXTURE_ROOT / "agentsec" / f"{manifest_id}-minimal.yaml",
    )


def manifest_has_fixture(
    manifest: AnalyzerManifest,
    *,
    fixture_root: Path | None = None,
) -> bool:
    """Return whether a parser fixture exists for ``manifest``."""
    root = fixture_root or _DEFAULT_FIXTURE_ROOT
    if manifest.id == "agentsec":
        return (root / "agentsec" / "agentsec-minimal.yaml").is_file()
    return any(
        (root / rel).is_file()
        for rel in (
            Path("sarif") / f"{manifest.id}-minimal.sarif.json",
            Path("native") / f"{manifest.id}-minimal.json",
            Path("native") / f"{manifest.id}-minimal.jsonl",
            Path("native") / f"{manifest.id}-minimal.txt",
        )
    )


def severity_map_complete(manifest: AnalyzerManifest) -> bool:
    """Return whether ``manifest.severity_map`` covers every native parser level."""
    try:
        validate_manifest(manifest, strict_severity_map=True, check_provenance=False)
    except ManifestValidationError:
        return False
    return True


def validate_manifest_ship_gate(
    manifest_path: Path,
    *,
    fixture_root: Path | None = None,
    doc_path: Path | None = None,
) -> None:
    """Validate one manifest satisfies fixture, doc row, and severity_map requirements."""
    manifest = load_manifest_file(manifest_path, strict_severity_map=False)
    root = fixture_root or _DEFAULT_FIXTURE_ROOT
    if not manifest_has_fixture(manifest, fixture_root=root):
        msg = f"{manifest.id} missing test fixture under {root}"
        raise CatalogIntegrityError(msg)
    if not severity_map_complete(manifest):
        msg = f"{manifest.id} severity_map incomplete for parser {manifest.parser!r}"
        raise CatalogIntegrityError(msg)
    docs = doc_path or _DEFAULT_DOC_PATH
    if docs.is_file():
        doc_ids = parse_analyzers_doc(docs)
        if manifest.id not in doc_ids:
            msg = f"{manifest.id} missing docs/ANALYZERS.md row"
            raise CatalogIntegrityError(msg)


def validate_catalog(
    *,
    fixture_root: Path | None = None,
    doc_path: Path | None = None,
) -> None:
    """Validate every shipped catalog manifest (CI gate)."""
    docs = doc_path or _DEFAULT_DOC_PATH
    root = fixture_root or _DEFAULT_FIXTURE_ROOT
    if not docs.is_file():
        msg = "docs/ANALYZERS.md must exist"
        raise CatalogIntegrityError(msg)
    doc_ids = parse_analyzers_doc(docs)
    catalog_dir = Path(__file__).resolve().parent / "catalog"
    for path in sorted(catalog_dir.glob("*.yaml")):
        validate_manifest_ship_gate(
            path,
            fixture_root=root,
            doc_path=docs,
        )
    catalog_ids = {m.id for m in load_catalog()}
    orphan_docs = sorted(doc_ids - catalog_ids)
    if orphan_docs:
        msg = f"docs/ANALYZERS.md lists unknown ids: {orphan_docs}"
        raise CatalogIntegrityError(msg)


def _default_enabled_label(value: bool | str) -> str:
    if value is True:
        return "enabled"
    if value is False:
        return "disabled"
    return "auto"


def _shell_trust_matrix_lines() -> list[str]:
    """Render the runtime x shell x trust x mode matrix from the live predicates.

    Every cell is computed by calling the predicates the pipeline itself calls
    (`evaluate_manifest_for_shell`, `evaluate_manifest_for_tier`,
    `evaluate_manifest_for_mode`) over the real catalog, so the published matrix
    cannot drift away from the code that enforces it (#35 D5, #38 D8/D9).
    """
    from mergecraft.analyzers.trust import (
        IN_PROCESS_ANALYZER_IDS,
        SHELL_DISABLED_ELIGIBLE_RUNTIMES,
        evaluate_manifest_for_mode,
        evaluate_manifest_for_shell,
        evaluate_manifest_for_tier,
        resolve_effective_analyzers_mode,
        resolve_selection_tier,
    )

    manifests = sorted(load_catalog(), key=lambda m: m.id)

    def _selected(*, tier: str, mode: str, shell: str) -> list[str]:
        """Replay the pipeline's own skip chain for one cell."""
        effective = resolve_effective_analyzers_mode(mode=mode, tier=tier)  # type: ignore[arg-type]  # — mode/tier are str loop vars; callee expects Literal narrowings
        selection_tier = resolve_selection_tier(mode=effective, tier=tier)  # type: ignore[arg-type]  # — effective/tier are str; callee expects Literal narrowings
        chosen: list[str] = []
        for manifest in manifests:
            if evaluate_manifest_for_tier(manifest=manifest, tier=selection_tier).skipped:
                continue
            if evaluate_manifest_for_shell(manifest=manifest, shell=shell).skipped:
                continue
            if evaluate_manifest_for_mode(manifest=manifest, mode=effective).skipped:
                continue
            chosen.append(manifest.id)
        return chosen

    total = len(manifests)
    counts: dict[tuple[str, str], int] = {}
    for manifest in manifests:
        key = (manifest.runtime, manifest.trust)
        counts[key] = counts.get(key, 0) + 1

    lines = [
        "",
        "## Runtime x shell x trust x mode",
        "",
        "Which analyzers run is decided on three independent axes. Each can skip a",
        "manifest with a named reason — a skip is an outcome, never a failure, and it",
        "appears as an `unavailable` row in the Analyzers pre-merge summary.",
        "",
        "- **shell** (`shell:` in the workflow) — may mergeCraft execute anything the",
        "  PR could have written? Enforced by `evaluate_manifest_for_shell()`.",
        "- **trust** (derived from the event) — `pull_request_target` and fork-head PRs",
        "  are `untrusted`. Enforced by `evaluate_manifest_for_tier()`.",
        "- **mode** (`analyzers:` in the workflow) — `off | auto | full |",
        "  untrusted-only`. Enforced by `evaluate_manifest_for_mode()` plus",
        "  `resolve_selection_tier()`.",
        "",
        "Under `shell: disabled`, eligible runtimes are "
        + " and ".join(
            f"`{value}`" for value in sorted(SHELL_DISABLED_ELIGIBLE_RUNTIMES, reverse=True)
        )
        + ".",
        "Their argv is copied verbatim out of a manifest mergeCraft ships, and a binary",
        "the repo provides may not stand in for the pinned one, so nothing the PR",
        "authored is executed. `runtime: repo-native` stays withheld because it exists",
        "to run the *repo's* tool against the *repo's* config.",
        "",
        "| runtime | trust | `shell: disabled` | `shell: restricted` / `enabled` |",
        "|---------|-------|-------------------|----------------------------------|",
    ]
    for runtime in ("repo-native", "managed", "container"):
        for trust in ("trusted", "untrusted"):
            count = counts.get((runtime, trust), 0)
            if not count:
                continue
            eligible = runtime in SHELL_DISABLED_ELIGIBLE_RUNTIMES
            if not eligible:
                disabled_cell = "withheld — `runtime` needs repo-provided tooling"
            elif trust == "trusted":
                disabled_cell = "runs on trusted events; skipped with a reason on untrusted ones"
            else:
                disabled_cell = "**runs** (pinned binary only)"
            other_cell = (
                "runs" if trust == "untrusted" else "runs on trusted events; skipped on untrusted"
            )
            lines.append(f"| `{runtime}` ({count}) | `{trust}` | {disabled_cell} | {other_cell} |")

    if IN_PROCESS_ANALYZER_IDS:
        exception_ids = ", ".join(f"`{value}`" for value in sorted(IN_PROCESS_ANALYZER_IDS))
        lines.extend(
            [
                "",
                f"One documented exception to the runtime row: {exception_ids}. It declares",
                "`runtime: repo-native` but `resolve_analyzer()` special-cases it before the",
                "repo-binary preference is consulted and `run_adapter()` executes it",
                "in-process — no subprocess, no argv, nothing the PR authored is run. The",
                "runtime axis asks whether PR content could steer what executes; for these",
                "the answer is no, so they stay eligible (#38).",
            ]
        )

    lines.extend(
        [
            "",
            "### The `analyzers:` mode axis",
            "",
            "`untrusted-only` runs only analyzers that need no secrets, no network and no",
            "PR-authored command construction: manifest selection is evaluated at the",
            "`untrusted` tier *and* the repo-tooling gate applies whatever the shell is.",
            "On `pull_request_target` and fork-head pull requests, `auto` resolves to it",
            "— a narrowing default, so a hardened workflow gets mechanical signal without",
            "loosening `shell:`. An unrecognised `analyzers:` value resolves there too,",
            "with a warning, rather than silently widening to `auto`.",
            "",
            "`full` requests more provisioning; it is never a trust override, and cannot",
            "re-admit a manifest the tier axis skipped.",
            "",
            f"Counts below are analyzers passing selection, out of {total} shipped, with",
            "`shell: restricted` (the shell axis inert) so the mode axis is isolated.",
            "",
            "| mode | trusted event | untrusted event (`pull_request_target`, fork) |",
            "|------|---------------|-----------------------------------------------|",
        ]
    )
    for mode in ("off", "auto", "full", "untrusted-only"):
        cells: list[str] = []
        for tier in ("trusted", "untrusted"):
            if mode == "off":
                cells.append("surface not registered")
                continue
            selected = _selected(tier=tier, mode=mode, shell="restricted")
            note = ""
            if mode == "auto" and tier == "untrusted":
                note = " — `auto` ⇒ `untrusted-only`"
            cells.append(f"{len(selected)} of {total}{note}")
        # Bolded so `parse_analyzers_doc()` does not read a mode name as an
        # analyzer id — it scrapes rows whose first cell is a bare code span.
        lines.append(f"| **`{mode}`** | {cells[0]} | {cells[1]} |")

    lines.extend(
        [
            "",
            "Passing these axes is necessary, not sufficient: a `container` manifest",
            "is eligible but still reports `unavailable` wherever no container runtime is",
            "present, and the seven `declared_unavailable` manifests keep their own skip",
            "reason. In the shipped Action image that leaves the `managed` rows as the",
            "analyzers a `shell: disabled` run actually executes.",
            "",
            "Repo-declared `staticChecks` are a third thing and are **always** withheld",
            "under `shell: disabled`, on every event: they run command strings the PR",
            "author controls. They report `declared-but-cannot-run` rather than vanishing.",
            "No `analyzers:` value re-enables them.",
        ]
    )
    return lines


def _related_providers_lines() -> list[str]:
    """Render the related-providers cross-reference note.

    Lives in the generator rather than in the markdown because
    ``docs/ANALYZERS.md`` is written wholesale by ``make catalog-check`` — a
    hand-written section there is erased on the next run (#57).
    """
    return [
        "",
        "> **Provider configuration (catalog slugs, credential detection, "
        "`mergecraft auth <provider>`) is documented in "
        "[the README → Authentication](../README.md#authentication).** "
        "This page is the *analyzer* catalog — the rows below are "
        "deterministic, manifest-driven tools (`actionlint`, `zizmor`, "
        "`ShellCheck`, `Hadolint`, …) the reviewer runs mechanically. The "
        "Nous Research / DeepSeek V4 Flash path (provider id `nous`, catalog "
        "slug `nous/deepseek/deepseek-v4-flash`) is a *provider*, not an "
        "analyzer, and lives in the README's "
        "[Authentication table](../README.md#authentication) alongside "
        "Anthropic, OpenAI, Google, and Cursor. Set up its secret with "
        "[`mergecraft auth nous`](../README.md#authentication); see "
        "[issue #57](https://github.com/alexhawat/mergeCraft/issues/57) for "
        "the rationale.",
    ]


def _sarif_upload_lines() -> list[str]:
    """Render the code-scanning upload section (#39, D13/D14).

    Lives in the generator rather than in the markdown because
    ``docs/ANALYZERS.md`` is written wholesale by ``make catalog-check`` — a
    hand-written section there is erased on the next run.
    """
    from mergecraft.analyzers.sarif_upload import UPLOADABLE_SOURCE

    return [
        "",
        "## SARIF upload to code scanning (#39)",
        "",
        "Opt-in, off by default. When enabled, mergeCraft exports the analyzer "
        "findings of a pull-request run as SARIF 2.1.0 and uploads them to GitHub "
        "code scanning, so mechanical findings stay readable when the review "
        "narrative is thin or when findings overflowed the inline comment budget.",
        "",
        "```yaml",
        "# .github/workflows/mergecraft.yml",
        "permissions:",
        "  contents: read",
        "  pull-requests: write",
        "  # Required for the upload. Without it GitHub answers 403 and mergeCraft",
        "  # logs a warning — the review still completes.",
        "  security-events: write",
        "",
        "jobs:",
        "  review:",
        "    steps:",
        "      - uses: alexhawat/mergeCraft@<sha>",
        "        with:",
        "          sarif_upload: enabled",
        "```",
        "",
        "Or in `.mergecraft/config.yaml` (the action input wins when it is set):",
        "",
        "```yaml",
        "analyzers:",
        "  sarifUpload: true",
        "```",
        "",
        "What is and is not uploaded:",
        "",
        f"- **Catalog analyzers only.** Only `source: {UPLOADABLE_SOURCE}` findings are "
        "eligible. `source: ci` findings carry truncated pipeline log excerpts and "
        "`source: agent` findings carry narrative; neither is uploaded, and raw logs "
        "never leave the process (D13).",
        "- **The clustered, placed set.** The upload reuses the findings the pipeline "
        "already clustered and placed, not the raw analyzer output, so cross-tool "
        "duplicates arrive as one alert (D14). It is *not* truncated at the inline "
        "comment budget — the overflow is exactly what this surface exists to show.",
        "- **Trust-gated.** Each finding's analyzer must still pass this run's "
        "`trust` x `shell` x `analyzers:` selection chain — the same predicates the "
        "pipeline calls, re-evaluated at upload time. A finding from a tool with no "
        "catalog manifest cannot be gated, so it is refused.",
        "- **Redacted before serialization.** `message`, `evidence`, `remediation` "
        "and `autofix` pass through `analyzers/redact.py` while still typed "
        "`Finding`s, before SARIF is built. `path` is left intact: it becomes "
        "`artifactLocation.uri`, and mangling it would detach the alert from its "
        "file.",
        "- **Never a gate.** A rejected upload — missing permission, code scanning "
        "unavailable, transport error — is logged at `warning` and the run continues.",
        "",
        "Check-run annotations are the documented alternative surface and are not "
        "implemented: they need `checks: write` instead, cap at 50 annotations per "
        "request, and largely repeat the inline review comments mergeCraft already "
        "posts.",
    ]


def generate_analyzers_doc(manifests: Iterable[AnalyzerManifest] | None = None) -> str:
    """Render ``docs/ANALYZERS.md`` from catalog manifests."""
    rows = sorted(manifests or load_catalog(), key=lambda m: m.id)
    lines = [
        "# Analyzer catalog",
        "",
        "Shipped mergeCraft catalog analyzers. Rows are generated from manifests — "
        "run ``uv run python -m mergecraft.analyzers.catalog_docs`` to refresh.",
        "",
    ]
    lines.extend(_related_providers_lines())
    lines.extend(
        [
            "",
            "| id | category | languages | default | runtime | trust | exclusive group | notes |",
            "|----|----------|-----------|---------|---------|-------|-----------------|-------|",
        ]
    )
    for manifest in rows:
        languages = ", ".join(manifest.languages) if manifest.languages else "—"
        group = manifest.exclusive_group or "—"
        notes: list[str] = []
        if manifest.declared_unavailable:
            notes.append(manifest.declared_unavailable)
        if manifest.id == "ast-grep":
            notes.append("Substrate for a future native policy engine — not built in C3.")
        if manifest.id == "sqlfluff":
            notes.append("Dialect is mandatory — skip when repo declares none.")
        if manifest.id == "presidio":
            notes.append("Container-only; high-confidence entity types only.")
        if manifest.id == "dotenv-linter":
            notes.append("Values never printed in findings (D8).")
        if manifest.id == "trufflehog":
            notes.append("verify off by default; impossible on fork PRs (C2).")
        if manifest.id == "phpstan":
            notes.append("No phpstan.neon/neon.dist → runs at --level=0 (D12).")
        if manifest.id in ("flake8", "pylint"):
            notes.append("Legacy opt-in — disabled by default; enable via config override.")
        if manifest.id in ("phpcs", "phpmd"):
            notes.append("Legacy opt-in — disabled by default; phpstan is the default PHP signal.")
        if manifest.id == "smarty-lint":
            notes.append(
                "*.tpl extension is ambiguous (Go templates, Terraform, Smarty) — "
                "enable only when .smarty-lint.json confirms Smarty intent."
            )
        note_text = " ".join(notes) if notes else "—"
        lines.append(
            f"| `{manifest.id}` | {manifest.category} | {languages} | "
            f"{_default_enabled_label(manifest.default_enabled)} | {manifest.runtime} | "
            f"{manifest.trust} | {group} | {note_text} |"
        )
    lines.extend(_shell_trust_matrix_lines())
    lines.extend(
        [
            "",
            "## Overrides",
            "",
            "Enable or disable tools in ``.mergecraft/config.yaml``:",
            "",
            "```yaml",
            "analyzers:",
            "  overrides:",
            "    golangci-lint:",
            "      enabled: true",
            "```",
            "",
            "See [CONTRIBUTING-ANALYZERS.md](CONTRIBUTING-ANALYZERS.md) to add a tool.",
            "",
            "## Execution preference",
            "",
            "For any given gate, in order — the first that can produce a verdict wins:",
            "",
            "1. **`repo-native`** — the repo's own pinned toolchain, when this "
            "environment can run it.",
            "2. **An existing CI result** — a check run the repo *declared* as proof of "
            "that gate (#36).",
            "3. **A managed pinned binary**, then **a container**.",
            "4. **Skip, with a named reason.** A skip is never a finding.",
            "",
            "## CI evidence (#36)",
            "",
            "The Action image usually lacks `make`, the repo's venv, and its pinned "
            "toolchains, so a repo-native gate reports `unavailable` even when the "
            "consumer's own CI just proved the same thing. Declaring the mapping lets "
            "that finished CI stand in:",
            "",
            "```yaml",
            "ciEvidence:",
            "  gates:",
            "    # <mergeCraft gate name>: <exact GitHub check-run name>",
            "    lint: Verify (drift gates)",
            "  sarifArtifacts:",
            "    - ruff-sarif",
            "```",
            "",
            "- **Declared only.** mergeCraft never infers that a check run *named* "
            "`lint` proves the `lint` gate — a pull request can add a workflow with "
            "any name it likes. With no `ciEvidence` block nothing is read and no "
            "extra API call is made.",
            "- **Green only substitutes.** A declared check run that passed rewrites "
            "the gate row to `satisfied-by-ci`. A declared check run that *failed* "
            "leaves the row alone and is reported as a `source: ci` finding instead.",
            "- **Reported, not blamed.** Findings derived from CI start non-blocking "
            "with `introduced_by_pr: unknown`; only the CI-intelligence blame layer "
            "(`ci/blame.py`, `ci/flaky.py`) may attribute one to this PR.",
            "- **Redacted.** Log excerpts are truncated and passed through "
            "`analyzers/redact.py` before they enter a finding.",
        ]
    )
    lines.extend(_sarif_upload_lines())
    return "\n".join(lines) + "\n"


def write_analyzers_doc(path: Path | None = None) -> Path:
    """Write generated catalog documentation."""
    target = path or _DEFAULT_DOC_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(generate_analyzers_doc(), encoding="utf-8")
    return target


def main() -> None:
    """CLI entry: regenerate ANALYZERS.md and validate the catalog."""
    write_analyzers_doc()
    validate_catalog()
    from loguru import logger

    logger.info("catalog OK — {} manifests", len(load_catalog()))


if __name__ == "__main__":
    main()
