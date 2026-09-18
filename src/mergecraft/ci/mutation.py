"""Parse declared mutation artifacts and emit survivors on changed functions.

The Action never runs a consumer's tests (C-D1). This module ingests a
finished mutmut or Stryker receipt and attributes survivors only to
functions the diff actually touched (C-D4). Undeclared means no API call.
A declared failed check is a finding, never a substitution (C-D2).
Shadow mode keeps survivors out of change-scoped blockers (C-D5).
Kill and escape rates are Python arithmetic only — never Jev (C-D9).

This module must not import ``scripts/mutate_decision_modules.py`` (K6).

Module: mergecraft.ci.mutation
Depends: mergecraft.analyzers.finding, mergecraft.ci.{archive_bounds,
    changed_functions,evidence}, loguru

Exports:
    Classes:
        MutationSurvivor — One surviving mutant row.
        ParsedMutation — Parser output, including a named skip reason.
        MutationIngestResult — Findings, skip reason, substitutions.
    Functions:
        parse_mutmut_json — mutmut ``mutants`` list.
        parse_stryker_json — Stryker v2 ``files`` map.
        parse_mutation_artifact — Sniff format from filename and contents.
        mutation_findings — Survivors on changed functions only.
        collect_ci_mutation_findings — Declared-artifact ingest (successful-only).
        kill_rate / escape_rate — Deterministic rates; ``total=0`` is ``None``.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from io import BytesIO
from typing import TYPE_CHECKING, Any, Literal
from zipfile import BadZipFile, ZipFile

from loguru import logger

from mergecraft.analyzers.finding import Finding, make_finding
from mergecraft.ci.archive_bounds import extract_zip_texts
from mergecraft.ci.changed_functions import (
    ChangedFunction,
    changed_functions_from_diff,
    resolve_enclosing_symbol,
)
from mergecraft.ci.evidence import CI_TOOL, GateSubstitution, artifact_ingest_failures

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from mergecraft.mcp.context import ToolContext
    from mergecraft.review_taxonomy import FindingSource
    from mergecraft.utils.github import GitHubClient

SKIP_UNSUPPORTED_MUTATION_FORMAT = "unsupported_mutation_format"

_MUTATION_CATEGORY = "Maintainability & Code Quality"
_SURVIVED = "survived"
_KILLED = "killed"
_FUNCTION_DECL = re.compile(r"\b(?:async\s+)?(?:function|def)\s+([A-Za-z_][A-Za-z0-9_]*)")


@dataclass(frozen=True, slots=True)
class MutationSurvivor:
    """One mutant that tests did not kill."""

    function: str
    status: str
    path: str = ""
    line: int | None = None


@dataclass(frozen=True, slots=True)
class ParsedMutation:
    """Result of parsing one mutation report."""

    skip_reason: str | None = None
    format: Literal["mutmut", "stryker"] | None = None
    survivors: list[MutationSurvivor] = field(default_factory=list)
    killed: int = 0
    total: int = 0


@dataclass(frozen=True, slots=True)
class MutationIngestResult:
    """Findings plus skip / substitution tokens for one ingest pass."""

    findings: list[Finding] = field(default_factory=list)
    skip_reason: str | None = None
    reaches_has_blockers: bool = False
    substitutions: list[GateSubstitution] = field(default_factory=list)


def _norm_path(path: str) -> str:
    return path.replace("\\", "/").lstrip("./")


def _status_of(raw: object) -> str:
    return str(raw or "").strip().lower()


def _as_line(raw: object) -> int | None:
    if isinstance(raw, bool) or not isinstance(raw, (int, float, str)):
        return None
    try:
        line = int(raw)
    except (TypeError, ValueError):
        return None
    return line if line > 0 else None


def kill_rate(killed: int, total: int) -> float | None:
    """Return ``killed / total``, or ``None`` when ``total`` is zero."""
    if total == 0:
        return None
    return killed / total


def escape_rate(killed: int, total: int) -> float | None:
    """Return ``1 - killed / total``, or ``None`` when ``total`` is zero."""
    if total == 0:
        return None
    return (total - killed) / total


def _function_from_source(source: str, line: int | None) -> str:
    if not source.strip() or line is None:
        return ""
    lines = source.splitlines()
    if not lines:
        return ""
    start = min(max(line - 1, 0), len(lines) - 1)
    for index in range(start, -1, -1):
        match = _FUNCTION_DECL.search(lines[index])
        if match:
            return match.group(1)
    return ""


def parse_mutmut_json(text: str) -> ParsedMutation:
    """Parse a mutmut JSON report (``mutants`` list)."""
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return ParsedMutation(skip_reason=SKIP_UNSUPPORTED_MUTATION_FORMAT)
    if not isinstance(payload, dict):
        return ParsedMutation(skip_reason=SKIP_UNSUPPORTED_MUTATION_FORMAT)
    mutants = payload.get("mutants")
    if not isinstance(mutants, list):
        return ParsedMutation(skip_reason=SKIP_UNSUPPORTED_MUTATION_FORMAT)

    survivors: list[MutationSurvivor] = []
    killed = 0
    total = 0
    for row in mutants:
        if not isinstance(row, dict):
            continue
        total += 1
        status = _status_of(row.get("status"))
        if status == _KILLED:
            killed += 1
        if status != _SURVIVED:
            continue
        function = str(row.get("function") or row.get("name") or "")
        path = _norm_path(str(row.get("filename") or row.get("file") or row.get("path") or ""))
        survivors.append(
            MutationSurvivor(
                function=function,
                status=str(row.get("status") or "survived"),
                path=path,
                line=_as_line(row.get("line")),
            )
        )
    return ParsedMutation(
        format="mutmut",
        survivors=survivors,
        killed=killed,
        total=total,
    )


def parse_stryker_json(text: str) -> ParsedMutation:
    """Parse a Stryker v2 JSON report (``files`` map)."""
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return ParsedMutation(skip_reason=SKIP_UNSUPPORTED_MUTATION_FORMAT)
    if not isinstance(payload, dict):
        return ParsedMutation(skip_reason=SKIP_UNSUPPORTED_MUTATION_FORMAT)
    files = payload.get("files")
    if not isinstance(files, dict):
        return ParsedMutation(skip_reason=SKIP_UNSUPPORTED_MUTATION_FORMAT)

    survivors: list[MutationSurvivor] = []
    killed = 0
    total = 0
    for raw_path, file_row in files.items():
        if not isinstance(file_row, dict):
            continue
        mutants = file_row.get("mutants")
        if not isinstance(mutants, list):
            continue
        source = str(file_row.get("source") or "")
        path = _norm_path(str(raw_path))
        for row in mutants:
            if not isinstance(row, dict):
                continue
            total += 1
            status = _status_of(row.get("status"))
            if status == _KILLED:
                killed += 1
            if status != _SURVIVED:
                continue
            location = row.get("location")
            start = location.get("start") if isinstance(location, dict) else None
            line = _as_line(start.get("line") if isinstance(start, dict) else None)
            function = str(row.get("function") or "") or _function_from_source(source, line)
            survivors.append(
                MutationSurvivor(
                    function=function,
                    status=str(row.get("status") or "Survived"),
                    path=path,
                    line=line,
                )
            )
    return ParsedMutation(
        format="stryker",
        survivors=survivors,
        killed=killed,
        total=total,
    )


def _looks_like_stryker(payload: object, filename: str) -> bool:
    if "stryker" in filename:
        return True
    if not isinstance(payload, dict):
        return False
    if payload.get("schemaVersion") is not None:
        return True
    files = payload.get("files")
    return isinstance(files, dict)


def _looks_like_mutmut(payload: object, filename: str) -> bool:
    if "mutmut" in filename:
        return True
    if not isinstance(payload, dict):
        return False
    return isinstance(payload.get("mutants"), list)


def parse_mutation_artifact(text: str, filename: str = "") -> ParsedMutation:
    """Sniff a mutation document and parse it, or skip as unsupported."""
    lowered = filename.lower()
    stripped = text.lstrip()
    head = stripped[:200].lower()

    if (
        lowered.endswith((".xml", ".html"))
        or stripped.startswith(("<?xml", "<"))
        or head.startswith(("<!doctype", "<testsuite", "<html"))
    ):
        return ParsedMutation(skip_reason=SKIP_UNSUPPORTED_MUTATION_FORMAT)

    if not (lowered.endswith(".json") or stripped.startswith(("{", "["))):
        return ParsedMutation(skip_reason=SKIP_UNSUPPORTED_MUTATION_FORMAT)

    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return ParsedMutation(skip_reason=SKIP_UNSUPPORTED_MUTATION_FORMAT)

    if _looks_like_stryker(payload, lowered) and not _looks_like_mutmut(payload, lowered):
        return parse_stryker_json(text)
    if _looks_like_mutmut(payload, lowered):
        return parse_mutmut_json(text)
    if _looks_like_stryker(payload, lowered):
        return parse_stryker_json(text)
    return ParsedMutation(skip_reason=SKIP_UNSUPPORTED_MUTATION_FORMAT)


def _shadow_scope(mode: str) -> Literal["run", "change"]:
    return "run" if mode == "shadow" else "change"


def _changed_symbols(
    changed_functions: Sequence[tuple[str, str] | Any],
    *,
    diff: str,
    source_tree: Mapping[str, str] | None,
) -> list[ChangedFunction]:
    symbols: list[ChangedFunction] = []
    for item in changed_functions:
        if isinstance(item, ChangedFunction):
            symbols.append(item)
            continue
        path = getattr(item, "path", None)
        name = getattr(item, "name", None)
        start_line = getattr(item, "start_line", None)
        if path is not None and name is not None:
            symbols.append(
                ChangedFunction(
                    name=str(name),
                    path=str(path),
                    start_line=int(start_line) if start_line is not None else 0,
                )
            )
            continue
        if isinstance(item, tuple) and len(item) >= 2:
            symbols.append(ChangedFunction(name=str(item[1]), path=str(item[0]), start_line=0))
    if symbols:
        return symbols
    if not diff.strip():
        return []
    return changed_functions_from_diff(diff, dict(source_tree or {}))


def _survivor_matches_changed(
    survivor: MutationSurvivor,
    symbol: ChangedFunction,
    *,
    source_tree: Mapping[str, str] | None,
) -> bool:
    if _norm_path(survivor.path) != _norm_path(symbol.path):
        return False
    if survivor.function != symbol.name:
        return False
    if symbol.start_line <= 0:
        return True
    if survivor.line is not None:
        source = (source_tree or {}).get(symbol.path)
        if source is not None:
            enclosing = resolve_enclosing_symbol(symbol.path, survivor.line, source)
            if enclosing is not None:
                return enclosing.name == symbol.name and enclosing.start_line == symbol.start_line
        return survivor.line == symbol.start_line
    return False


def mutation_findings(
    parsed: ParsedMutation,
    changed_functions: Sequence[tuple[str, str] | Any] | None = None,
    *,
    source: FindingSource = "ci",
    mode: str = "shadow",
    survivor_threshold: int = 0,
    diff: str = "",
    source_tree: Mapping[str, str] | None = None,
) -> MutationIngestResult:
    """Emit survivor findings for changed functions only.

    Unchanged functions are not emitted (C-D4). ``survivor_threshold`` is the
    minimum attributed-survivor count required to emit; the default ``0``
    means any changed-function survivor is evidence.
    """
    if parsed.skip_reason is not None:
        return MutationIngestResult(skip_reason=parsed.skip_reason)

    symbols = _changed_symbols(
        changed_functions or [],
        diff=diff,
        source_tree=source_tree,
    )
    attributed: list[tuple[str, MutationSurvivor]] = []
    for item in parsed.survivors:
        path = _norm_path(item.path)
        candidates = [
            symbol
            for symbol in symbols
            if _norm_path(symbol.path) == path and symbol.name == item.function
        ]
        if not candidates:
            continue
        if len(candidates) == 1:
            if _survivor_matches_changed(item, candidates[0], source_tree=source_tree):
                attributed.append((path, item))
            continue
        matched = [
            symbol
            for symbol in candidates
            if _survivor_matches_changed(item, symbol, source_tree=source_tree)
        ]
        if len(matched) == 1:
            attributed.append((path, item))

    if len(attributed) < survivor_threshold or not attributed:
        return MutationIngestResult()

    findings: list[Finding] = []
    for path, item in attributed:
        line = item.line or 1
        message = f"Surviving mutant on `{item.function}` — tests did not kill this mutation"
        findings.append(
            make_finding(
                tool=CI_TOOL,
                rule_id="survivor",
                category=_MUTATION_CATEGORY,
                severity="Minor",
                confidence="certain",
                message=message,
                path=path,
                start_line=line,
                end_line=line,
                source=source,
                evidence=[
                    f"function={item.function}",
                    f"status={item.status}",
                    f"format={parsed.format or 'unknown'}",
                ],
                introduced_by_pr="true",
                scope=_shadow_scope(mode),
            )
        )

    # Shadow findings are scope="run" so they stay out of change-scoped
    # blockers without touching BLOCKING_SEVERITIES / blocking_findings.
    reaches = False if mode == "shadow" else bool(findings)
    return MutationIngestResult(findings=findings, reaches_has_blockers=reaches)


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


def _mode_from_context(ctx: ToolContext) -> str:
    snapshot = ctx.repo_settings_snapshot
    if snapshot is None:
        return "shadow"
    return snapshot.settings.mutation.mode


def _threshold_from_context(ctx: ToolContext) -> int:
    snapshot = ctx.repo_settings_snapshot
    if snapshot is None:
        return 0
    return snapshot.settings.mutation.survivor_threshold


async def collect_ci_mutation_findings(
    ctx: ToolContext,
    *,
    client: GitHubClient,
    runs: Sequence[Mapping[str, Any]],
    artifacts: Sequence[str],
    changed_functions: Sequence[tuple[str, str] | Any] | None = None,
    diff: str = "",
    source_tree: Mapping[str, str] | None = None,
    check_runs: Sequence[Mapping[str, Any]] | None = None,
) -> MutationIngestResult:
    """Ingest declared, successful mutation artifacts for this head.

    Empty ``artifacts`` makes no GitHub call (C-D2). A declared check that
    failed becomes a finding and never a gate substitution. Safe to schedule
    concurrently with the same ``client`` — this function does not rebind
    tokens or close the client.
    """
    wanted = [name.strip() for name in artifacts if name.strip()]
    if not wanted:
        return MutationIngestResult()

    wanted_set = set(wanted)
    findings, failed_names = artifact_ingest_failures(check_runs, wanted_set)
    download_names = wanted_set - failed_names
    parsed_rows: list[ParsedMutation] = []
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
                    "ci evidence: mutation listing failed for run {} — {}",
                    run_id,
                    listing_err,
                )
                continue
            if listed.incomplete:
                logger.warning(
                    "ci evidence: mutation listing truncated for run {} — not treating as complete",
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
                        "ci evidence: mutation artifact {} ingest failed — {}",
                        name,
                        artifact_err,
                    )
                    continue
                for filename, document in _documents_from_zip(archive):
                    parsed_rows.append(parse_mutation_artifact(document, filename=filename))

    mode = _mode_from_context(ctx)
    threshold = _threshold_from_context(ctx)
    skip_reason: str | None = None
    survivor_findings: list[Finding] = []
    reaches = False
    for parsed in parsed_rows:
        result = mutation_findings(
            parsed,
            changed_functions or [],
            source="ci",
            mode=mode,
            survivor_threshold=threshold,
            diff=diff,
            source_tree=source_tree,
        )
        survivor_findings.extend(result.findings)
        if result.skip_reason and skip_reason is None and not result.findings:
            skip_reason = result.skip_reason
        reaches = reaches or result.reaches_has_blockers

    combined = [*findings, *survivor_findings]
    if mode == "shadow":
        reaches = False
    return MutationIngestResult(
        findings=combined,
        skip_reason=skip_reason if not combined else None,
        reaches_has_blockers=reaches,
        substitutions=[],
    )


__all__ = [
    "SKIP_UNSUPPORTED_MUTATION_FORMAT",
    "MutationIngestResult",
    "MutationSurvivor",
    "ParsedMutation",
    "collect_ci_mutation_findings",
    "escape_rate",
    "kill_rate",
    "mutation_findings",
    "parse_mutation_artifact",
    "parse_mutmut_json",
    "parse_stryker_json",
]
