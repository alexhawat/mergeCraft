"""Native and SARIF analyzer output parsers."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from mergecraft.analyzers.finding import Finding
from mergecraft.analyzers.parsers.buf_native import parse_buf_native
from mergecraft.analyzers.parsers.eslint_json import parse_eslint_json
from mergecraft.analyzers.parsers.mypy_json import parse_mypy_json
from mergecraft.analyzers.parsers.oasdiff_json import parse_oasdiff_json
from mergecraft.analyzers.parsers.osv_json import parse_osv_json
from mergecraft.analyzers.parsers.pyright_json import parse_pyright_json
from mergecraft.analyzers.parsers.ruff_json import parse_ruff_json
from mergecraft.analyzers.parsers.sarif import parse_sarif
from mergecraft.analyzers.parsers.shellcheck_json import parse_shellcheck_json
from mergecraft.analyzers.parsers.squawk_json import parse_squawk_json
from mergecraft.analyzers.parsers.trivy_json import parse_trivy_json
from mergecraft.analyzers.parsers.trufflehog_jsonl import parse_trufflehog_jsonl

if TYPE_CHECKING:
    from pathlib import Path

    from mergecraft.analyzers.manifest import AnalyzerManifest

ParserFn = Callable[..., list[Finding]]

_PARSERS: dict[str, ParserFn] = {
    "buf_native": parse_buf_native,
    "sarif": parse_sarif,
    "ruff_json": parse_ruff_json,
    "eslint_json": parse_eslint_json,
    "mypy_json": parse_mypy_json,
    "pyright_json": parse_pyright_json,
    "oasdiff_json": parse_oasdiff_json,
    "osv_json": parse_osv_json,
    "squawk_json": parse_squawk_json,
    "trivy_json": parse_trivy_json,
    "trufflehog_jsonl": parse_trufflehog_jsonl,
    "shellcheck_json": parse_shellcheck_json,
}


def get_parser(parser_id: str) -> ParserFn:
    parser = _PARSERS.get(parser_id)
    if parser is None:
        msg = f"unknown analyzer parser: {parser_id!r}"
        raise KeyError(msg)
    return parser


def parse_output(
    raw: str,
    *,
    manifest: AnalyzerManifest,
    repo_root: Path,
) -> list[Finding]:
    """Parse analyzer output text using the manifest's configured parser."""
    return get_parser(manifest.parser)(raw, manifest=manifest, repo_root=repo_root)


__all__ = ["get_parser", "parse_output"]
