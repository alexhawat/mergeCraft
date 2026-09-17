"""Parse declared coverage artifacts and emit CRAP findings on changed functions.

The Action never runs a consumer's tests (C-D1). This module ingests a
finished coverage receipt — coverage.py JSON, lcov, or Cobertura — and
scores only functions the diff actually touched (C-D4). Undeclared means
no API call. A declared failed check is a finding, never a substitution
(C-D2). Shadow mode keeps scores out of change-scoped blockers (C-D5).

Module: mergecraft.ci.coverage
Depends: mergecraft.analyzers.finding, mergecraft.analyzers.scope,
    mergecraft.ci.{archive_bounds,changed_functions,crap,evidence},
    mergecraft.mcp.tool_state, loguru

Exports:
    Classes:
        CoverageFunction — One per-function coverage row.
        ParsedCoverage — Parser output, including a named skip reason.
        CoverageIngestResult — Findings, skip reason, run notes, substitutions.
    Functions:
        parse_coverage_py_json — coverage.py ``files.<path>.functions``.
        parse_lcov — lcov ``FN:`` / ``FNDA:`` records.
        parse_cobertura — Cobertura ``<method>`` elements.
        parse_coverage_artifact — Sniff format from filename and contents.
        coverage_findings — CRAP findings for changed functions only.
        collect_ci_coverage_findings — Declared-artifact ingest (successful-only).
        coverage_inputs_from_context — Diff + source tree from the checkout.
"""

from __future__ import annotations

import ast
import json
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal
from zipfile import BadZipFile, ZipFile

from defusedxml.ElementTree import ParseError, fromstring
from loguru import logger

from mergecraft.analyzers.finding import Finding, make_finding
from mergecraft.analyzers.scope import parse_diff_scope
from mergecraft.ci.archive_bounds import extract_zip_texts
from mergecraft.ci.changed_functions import changed_functions_from_diff
from mergecraft.ci.crap import (
    DEFAULT_CRAP_BANDS,
    CrapBands,
    CrapError,
    crap_band,
    crap_finding_severity,
    crap_score,
)
from mergecraft.ci.evidence import CI_TOOL, GateSubstitution, check_run_to_finding

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from mergecraft.mcp.context import ToolContext
    from mergecraft.review_taxonomy import FindingSource
    from mergecraft.utils.github import GitHubClient

SKIP_COVERAGE_NO_FUNCTION_RECORDS = "coverage_no_function_records"
SKIP_LCOV_NO_FUNCTION_RECORDS = "lcov_no_function_records"
SKIP_COBERTURA_NO_METHOD_ELEMENTS = "cobertura_no_method_elements"
SKIP_UNSUPPORTED_COVERAGE_FORMAT = "unsupported_coverage_format"
SKIP_ENCLOSING_SYMBOL_UNRESOLVED = "enclosing_symbol_unresolved"

NOTE_COVERAGE_UNDECLARED = "coverage_undeclared"
NOTE_COVERAGE_CLEAN = "coverage_clean"
NOTE_COVERAGE_DEFAULT_BANDS = "coverage_default_bands"
NOTE_COVERAGE_CONSUMER_BANDS = "coverage_consumer_bands"

_COVERAGE_CATEGORY = "Maintainability & Code Quality"
_DECISION_NODES = (
    ast.If,
    ast.For,
    ast.AsyncFor,
    ast.While,
    ast.ExceptHandler,
    ast.Assert,
    ast.IfExp,
)


@dataclass(frozen=True, slots=True)
class CoverageFunction:
    """One function's coverage (and optional reported complexity)."""

    name: str
    path: str
    coverage: float
    complexity: int | None = None


@dataclass(frozen=True, slots=True)
class ParsedCoverage:
    """Result of parsing one coverage document."""

    functions: list[CoverageFunction] = field(default_factory=list)
    skip_reason: str | None = None


@dataclass(frozen=True, slots=True)
class CoverageIngestResult:
    """Findings plus the C0 run-note / skip tokens for one ingest pass."""

    findings: list[Finding] = field(default_factory=list)
    skip_reason: str | None = None
    run_notes: list[str] = field(default_factory=list)
    reaches_has_blockers: bool = False
    substitutions: list[GateSubstitution] = field(default_factory=list)


def _norm_path(path: str) -> str:
    return path.replace("\\", "/").lstrip("./")


def _xml_local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _as_finite_float(raw: object) -> float | None:
    if isinstance(raw, bool) or not isinstance(raw, (int, float, str)):
        return None
    try:
        value = float(raw)
    except ValueError:
        return None
    if value != value:
        return None
    return value


def _coverage_ratio(raw: object) -> float | None:
    value = _as_finite_float(raw)
    if value is None:
        return None
    if value != value:
        return None
    if value > 1.0:
        value = value / 100.0
    if value < 0.0 or value > 1.0:
        return None
    return value


def _mccabe(node: ast.AST) -> int:
    score = 1
    for child in ast.walk(node):
        if isinstance(child, _DECISION_NODES):
            score += 1
    return score


def complexity_from_source(source: str, *, name: str, start_line: int) -> int | None:
    """Return McCabe complexity for the function at ``start_line``, if parseable."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return None
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name == name and int(node.lineno) == start_line:
            return _mccabe(node)
    return None


def parse_coverage_py_json(text: str) -> ParsedCoverage:
    """Parse coverage.py JSON (``files.<path>.functions``)."""
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return ParsedCoverage(skip_reason=SKIP_UNSUPPORTED_COVERAGE_FORMAT)
    if not isinstance(payload, dict):
        return ParsedCoverage(skip_reason=SKIP_UNSUPPORTED_COVERAGE_FORMAT)
    files = payload.get("files")
    if not isinstance(files, dict):
        return ParsedCoverage(skip_reason=SKIP_COVERAGE_NO_FUNCTION_RECORDS)

    saw_functions_key = False
    functions: list[CoverageFunction] = []
    for raw_path, file_row in files.items():
        if not isinstance(file_row, dict):
            continue
        if "functions" not in file_row:
            continue
        saw_functions_key = True
        records = file_row.get("functions")
        if not isinstance(records, dict):
            continue
        path = _norm_path(str(raw_path))
        for raw_name, record in records.items():
            if not isinstance(record, dict):
                continue
            raw_summary = record.get("summary")
            summary = raw_summary if isinstance(raw_summary, dict) else {}
            ratio = _coverage_ratio(summary.get("percent_covered"))
            if ratio is None:
                covered = _as_finite_float(summary.get("covered_lines"))
                statements = _as_finite_float(summary.get("num_statements"))
                ratio = covered / statements if covered is not None and statements else 0.0
            complexity_raw = record.get("complexity")
            complexity: int | None
            try:
                complexity = int(complexity_raw) if complexity_raw is not None else None
            except (TypeError, ValueError):
                complexity = None
            functions.append(
                CoverageFunction(
                    name=str(raw_name),
                    path=path,
                    coverage=ratio,
                    complexity=complexity,
                )
            )
    if not saw_functions_key:
        return ParsedCoverage(skip_reason=SKIP_COVERAGE_NO_FUNCTION_RECORDS)
    return ParsedCoverage(functions=functions)


def parse_lcov(text: str) -> ParsedCoverage:
    """Parse lcov ``FN:`` / ``FNDA:`` records into per-function coverage."""
    functions: list[CoverageFunction] = []
    current_path = ""
    declared: list[tuple[int, str]] = []
    hits: dict[str, int] = {}
    line_hits: dict[int, int] = {}

    def _flush() -> None:
        if not declared:
            return
        starts = [start for start, _ in declared]
        for index, (start, name) in enumerate(declared):
            next_start = starts[index + 1] if index + 1 < len(starts) else None
            covered = 0
            statements = 0
            for line, count in line_hits.items():
                if line < start:
                    continue
                if next_start is not None and line >= next_start:
                    continue
                statements += 1
                if count > 0:
                    covered += 1
            ratio = covered / statements if statements else (1.0 if hits.get(name, 0) > 0 else 0.0)
            functions.append(CoverageFunction(name=name, path=current_path, coverage=ratio))

    saw_fn = False
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith("SF:"):
            _flush()
            declared = []
            hits = {}
            line_hits = {}
            current_path = _norm_path(line[3:])
            continue
        if line.startswith("FN:"):
            saw_fn = True
            payload = line[3:]
            start_text, _, name = payload.partition(",")
            try:
                start = int(start_text)
            except ValueError:
                continue
            if name:
                declared.append((start, name))
            continue
        if line.startswith("FNDA:"):
            count_text, _, name = line[5:].partition(",")
            try:
                hits[name] = int(count_text)
            except ValueError:
                hits[name] = 0
            continue
        if line.startswith("DA:"):
            payload = line[3:]
            line_text, _, count_text = payload.partition(",")
            try:
                line_hits[int(line_text)] = int(count_text.split(",")[0])
            except ValueError:
                continue
            continue
        if line == "end_of_record":
            _flush()
            declared = []
            hits = {}
            line_hits = {}
            current_path = ""

    _flush()
    if not saw_fn:
        return ParsedCoverage(skip_reason=SKIP_LCOV_NO_FUNCTION_RECORDS)
    return ParsedCoverage(functions=functions)


def parse_cobertura(text: str) -> ParsedCoverage:
    """Parse Cobertura ``<method>`` elements."""
    try:
        root = fromstring(text)
    except ParseError:
        return ParsedCoverage(skip_reason=SKIP_UNSUPPORTED_COVERAGE_FORMAT)

    functions: list[CoverageFunction] = []
    saw_method = False
    for class_el in root.iter():
        if _xml_local(class_el.tag) != "class":
            continue
        path = _norm_path(str(class_el.get("filename") or ""))
        class_complexity = class_el.get("complexity")
        for child in class_el:
            if _xml_local(child.tag) != "methods":
                continue
            for method in child:
                if _xml_local(method.tag) != "method":
                    continue
                saw_method = True
                name = str(method.get("name") or "")
                if not name:
                    continue
                ratio = _coverage_ratio(method.get("line-rate"))
                if ratio is None:
                    ratio = 0.0
                complexity_raw = method.get("complexity", class_complexity)
                complexity: int | None
                try:
                    complexity = int(float(complexity_raw)) if complexity_raw is not None else None
                except (TypeError, ValueError):
                    complexity = None
                functions.append(
                    CoverageFunction(
                        name=name,
                        path=path,
                        coverage=ratio,
                        complexity=complexity,
                    )
                )
    if not saw_method:
        return ParsedCoverage(skip_reason=SKIP_COBERTURA_NO_METHOD_ELEMENTS)
    return ParsedCoverage(functions=functions)


def parse_coverage_artifact(text: str, filename: str = "") -> ParsedCoverage:
    """Sniff a coverage document and parse it, or skip as unsupported."""
    lowered = filename.lower()
    stripped = text.lstrip()
    head = stripped[:200].lower()

    if lowered.endswith(".html") or head.startswith(("<!doctype html", "<html")):
        return ParsedCoverage(skip_reason=SKIP_UNSUPPORTED_COVERAGE_FORMAT)
    if (
        lowered.endswith((".xml", ".cobertura"))
        or "cobertura" in lowered
        or stripped.startswith("<?xml")
        or "<coverage" in head
    ):
        return parse_cobertura(text)
    if (
        lowered.endswith((".info", ".lcov"))
        or "lcov" in lowered
        or stripped.startswith(("TN:", "SF:"))
    ):
        return parse_lcov(text)
    if lowered.endswith(".json") or stripped.startswith("{"):
        return parse_coverage_py_json(text)
    return ParsedCoverage(skip_reason=SKIP_UNSUPPORTED_COVERAGE_FORMAT)


def _lookup_coverage(
    functions: Sequence[CoverageFunction],
    *,
    path: str,
    name: str,
) -> CoverageFunction | None:
    want_path = _norm_path(path)
    for item in functions:
        if item.name == name and _norm_path(item.path) == want_path:
            return item
    return None


def _shadow_scope(mode: str) -> Literal["run", "change"]:
    return "run" if mode == "shadow" else "change"


def coverage_findings(
    parsed: ParsedCoverage,
    *,
    diff: str = "",
    source_tree: Mapping[str, str] | None = None,
    source: FindingSource = "ci",
    mode: str = "shadow",
    bands: CrapBands | Mapping[str, float] | None = None,
) -> CoverageIngestResult:
    """Score changed functions and emit watch+ CRAP findings.

    Clean-band functions produce no finding. Unresolvable hunks emit nothing
    (never file scope) and record ``enclosing_symbol_unresolved``.
    """
    if parsed.skip_reason is not None:
        return CoverageIngestResult(skip_reason=parsed.skip_reason)

    tree = dict(source_tree or {})
    symbols = changed_functions_from_diff(diff, tree)
    notes: list[str] = []
    if bands is None:
        notes.append(NOTE_COVERAGE_DEFAULT_BANDS)
    else:
        notes.append(NOTE_COVERAGE_CONSUMER_BANDS)

    if diff.strip() and not symbols:
        return CoverageIngestResult(
            skip_reason=SKIP_ENCLOSING_SYMBOL_UNRESOLVED,
            run_notes=notes,
        )

    findings: list[Finding] = []
    scored_clean = False
    for symbol in symbols:
        record = _lookup_coverage(parsed.functions, path=symbol.path, name=symbol.name)
        if record is None:
            continue
        complexity = record.complexity
        if complexity is None:
            source_text = tree.get(symbol.path)
            if source_text is not None:
                complexity = complexity_from_source(
                    source_text, name=symbol.name, start_line=symbol.start_line
                )
        if complexity is None:
            continue
        try:
            score = crap_score(complexity, record.coverage)
        except CrapError:
            logger.warning(
                "ci evidence: skipping CRAP for {} in {} — invalid inputs",
                symbol.name,
                symbol.path,
            )
            continue
        band = crap_band(score, bands=bands)
        if band == "clean":
            scored_clean = True
            continue
        percent = record.coverage * 100.0
        message = (
            f"CRAP {score:g} ({band}) on `{symbol.name}` — "
            f"complexity {complexity}, coverage {percent:g}%"
        )
        findings.append(
            make_finding(
                tool=CI_TOOL,
                rule_id=f"crap-{band}",
                category=_COVERAGE_CATEGORY,
                severity=crap_finding_severity(band),
                confidence="certain",
                message=message,
                path=symbol.path,
                start_line=symbol.start_line,
                end_line=symbol.start_line,
                source=source,
                evidence=[
                    f"crap={score:g}",
                    f"complexity={complexity}",
                    f"coverage={record.coverage:g}",
                    f"band={band}",
                ],
                introduced_by_pr="true",
                scope=_shadow_scope(mode),
            )
        )

    if not findings and scored_clean:
        notes.append(NOTE_COVERAGE_CLEAN)

    # Shadow findings are scope="run" so they stay out of change-scoped
    # blockers without touching BLOCKING_SEVERITIES / blocking_findings.
    reaches = False if mode == "shadow" else bool(findings)
    return CoverageIngestResult(
        findings=findings,
        run_notes=notes,
        reaches_has_blockers=reaches,
    )


def _documents_from_zip(archive: bytes) -> list[tuple[str, str]]:
    """Return ``(filename, text)`` pairs from a bounded artifact zip."""

    def _keep(name: str) -> bool:
        lowered = name.lower()
        if name.endswith("/"):
            return False
        return not lowered.endswith((".png", ".jpg", ".jpeg", ".gif", ".woff", ".ttf"))

    texts = extract_zip_texts(archive, name_filter=_keep)
    names: list[str] = []
    try:
        with ZipFile(BytesIO(archive)) as zf:
            names = [info.filename for info in zf.infolist() if _keep(info.filename)]
    except (BadZipFile, OSError):
        names = []
    named: list[tuple[str, str]] = []
    for index, text in enumerate(texts):
        filename = names[index] if index < len(names) else ""
        named.append((filename, text))
    return named


def coverage_inputs_from_context(ctx: ToolContext) -> tuple[str, dict[str, str]]:
    """Load the checkout's unified diff and the current text of hunk paths."""
    from mergecraft.mcp.tool_state import primary_repo_state

    state = primary_repo_state(ctx.tool_state)
    repo_root = Path(state.dir) if state.dir else Path()
    diff = ""
    if state.diff_path:
        diff_path = Path(state.diff_path)
        if diff_path.is_file():
            try:
                diff = diff_path.read_text(encoding="utf-8")
            except OSError as exc:
                logger.warning("ci evidence: failed to read diff {}: {}", diff_path, exc)

    source_tree: dict[str, str] = {}
    if not diff:
        return diff, source_tree
    for path in parse_diff_scope(diff).hunk_ranges:
        file_path = repo_root / path
        if not file_path.is_file():
            continue
        try:
            source_tree[path] = file_path.read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning("ci evidence: failed to read {}: {}", file_path, exc)
    return diff, source_tree


def _bands_from_context(ctx: ToolContext) -> CrapBands | Mapping[str, float] | None:
    snapshot = ctx.repo_settings_snapshot
    if snapshot is None:
        return None
    bands = snapshot.settings.coverage.bands
    if (
        bands.watch == DEFAULT_CRAP_BANDS.watch
        and bands.elevated == DEFAULT_CRAP_BANDS.elevated
        and bands.crap == DEFAULT_CRAP_BANDS.crap
        and bands.severe == DEFAULT_CRAP_BANDS.severe
    ):
        return None
    return {
        "watch": bands.watch,
        "elevated": bands.elevated,
        "crap": bands.crap,
        "severe": bands.severe,
    }


def _mode_from_context(ctx: ToolContext) -> str:
    snapshot = ctx.repo_settings_snapshot
    if snapshot is None:
        return "shadow"
    return snapshot.settings.coverage.mode


async def collect_ci_coverage_findings(
    ctx: ToolContext,
    *,
    client: GitHubClient,
    runs: Sequence[Mapping[str, Any]],
    artifacts: Sequence[str],
    diff: str,
    source_tree: Mapping[str, str] | None = None,
    check_runs: Sequence[Mapping[str, Any]] | None = None,
) -> CoverageIngestResult:
    """Ingest declared, successful coverage artifacts for this head.

    Empty ``artifacts`` makes no GitHub call (C-D2). A declared check that
    failed becomes a finding and never a gate substitution. Safe to schedule
    concurrently with the same ``client`` — this function does not rebind
    tokens or close the client.
    """
    wanted = [name.strip() for name in artifacts if name.strip()]
    if not wanted:
        return CoverageIngestResult(run_notes=[NOTE_COVERAGE_UNDECLARED])

    wanted_set = set(wanted)
    findings: list[Finding] = []
    failed_names: set[str] = set()
    for check_run in check_runs or []:
        name = str(check_run.get("name") or "").strip()
        if name not in wanted_set:
            continue
        finding = check_run_to_finding(check_run)
        if finding is None:
            continue
        findings.append(finding)
        failed_names.add(name)

    download_names = wanted_set - failed_names
    parsed_rows: list[ParsedCoverage] = []
    if download_names:
        for run in runs:
            run_id = run.get("id")
            if not isinstance(run_id, int):
                continue
            try:
                listed = await ctx.scm.list_workflow_run_artifacts(
                    ctx.repo.owner, ctx.repo.name, run_id
                )
            except Exception as listing_err:
                logger.warning(
                    "ci evidence: coverage listing failed for run {} — {}",
                    run_id,
                    listing_err,
                )
                continue
            if listed.incomplete:
                logger.warning(
                    "ci evidence: coverage listing truncated for run {} — not treating as complete",
                    run_id,
                )
                continue
            for artifact in listed.items:
                name = str(artifact.get("name") or "")
                artifact_id = artifact.get("id")
                if name not in download_names or not isinstance(artifact_id, int):
                    continue
                try:
                    archive = await client.download_artifact_zip(
                        ctx.repo.owner, ctx.repo.name, artifact_id
                    )
                except Exception as artifact_err:
                    logger.warning(
                        "ci evidence: coverage artifact {} ingest failed — {}",
                        name,
                        artifact_err,
                    )
                    continue
                for filename, document in _documents_from_zip(archive):
                    parsed_rows.append(parse_coverage_artifact(document, filename=filename))

    notes: list[str] = []
    skip_reason: str | None = None
    crap_findings: list[Finding] = []
    reaches = False
    mode = _mode_from_context(ctx)
    bands = _bands_from_context(ctx)
    for parsed in parsed_rows:
        result = coverage_findings(
            parsed,
            diff=diff,
            source_tree=source_tree,
            source="ci",
            mode=mode,
            bands=bands,
        )
        crap_findings.extend(result.findings)
        notes.extend(note for note in result.run_notes if note not in notes)
        if result.skip_reason and skip_reason is None and not result.findings:
            skip_reason = result.skip_reason
        reaches = reaches or result.reaches_has_blockers

    combined = [*findings, *crap_findings]
    if mode == "shadow":
        reaches = False
    return CoverageIngestResult(
        findings=combined,
        skip_reason=skip_reason if not combined else None,
        run_notes=notes,
        reaches_has_blockers=reaches,
        substitutions=[],
    )


__all__ = [
    "NOTE_COVERAGE_CLEAN",
    "NOTE_COVERAGE_CONSUMER_BANDS",
    "NOTE_COVERAGE_DEFAULT_BANDS",
    "NOTE_COVERAGE_UNDECLARED",
    "SKIP_COBERTURA_NO_METHOD_ELEMENTS",
    "SKIP_COVERAGE_NO_FUNCTION_RECORDS",
    "SKIP_ENCLOSING_SYMBOL_UNRESOLVED",
    "SKIP_LCOV_NO_FUNCTION_RECORDS",
    "SKIP_UNSUPPORTED_COVERAGE_FORMAT",
    "CoverageFunction",
    "CoverageIngestResult",
    "ParsedCoverage",
    "collect_ci_coverage_findings",
    "complexity_from_source",
    "coverage_findings",
    "coverage_inputs_from_context",
    "parse_cobertura",
    "parse_coverage_artifact",
    "parse_coverage_py_json",
    "parse_lcov",
]
