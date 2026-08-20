"""YAML manifest schema for catalog analyzers (D1)."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from mergecraft.review_taxonomy import FINDING_SEVERITIES

if TYPE_CHECKING:
    from pathlib import Path

TrustTier = Literal["trusted", "untrusted"]
RuntimeMode = Literal["repo-native", "managed", "container"]
DefaultEnabled = bool | Literal["auto"]

_BRACE_RE = re.compile(r"\{([^{}]+)\}")

# Native severities each parser may emit — repo-native manifests must map them all (D2).
_PARSER_NATIVE_SEVERITIES: dict[str, frozenset[str]] = {
    "sarif": frozenset({"error", "warning", "note"}),
    "ruff_json": frozenset({"error", "warning"}),
    "shellcheck_json": frozenset({"error", "warning", "info", "style"}),
    "eslint_json": frozenset({"error", "warning"}),
    "mypy_json": frozenset({"error", "warning", "note"}),
    "pyright_json": frozenset({"error", "warning", "information"}),
    "oasdiff_json": frozenset({"breaking", "warning", "info"}),
    "osv_json": frozenset({"critical", "high", "medium", "low"}),
    "squawk_json": frozenset({"error", "warning"}),
    "trivy_json": frozenset({"critical", "high", "medium", "low", "unknown"}),
    "trufflehog_jsonl": frozenset({"verified", "unverified"}),
    "agentsec_native": frozenset({"critical", "major", "minor"}),
    "buf_native": frozenset({"breaking", "lint"}),
    "bandit_json": frozenset({"high", "medium", "low", "undefined"}),
    "cargo_audit_json": frozenset({"error", "warning"}),
    "cargo_deny_json": frozenset({"error", "warning", "note"}),
    "vulture_text": frozenset({"warning"}),
    "tsc_pretty": frozenset({"error", "warning"}),
    "knip_json": frozenset({"error", "warning"}),
    "jscpd_json": frozenset({"warning"}),
    "bundler_audit_json": frozenset({"error", "warning"}),
    "sqlfluff_json": frozenset({"warning"}),
    "rustc_json": frozenset({"error", "warning", "note"}),
    "htmlhint_json": frozenset({"error", "warning"}),
    "stylelint_json": frozenset({"error", "warning"}),
    "yamllint_parsable": frozenset({"error", "warning"}),
    "markdownlint_json": frozenset({"error"}),
    "prisma_lint_json": frozenset({"error"}),
    "luacheck_text": frozenset({"error", "warning"}),
    "checkmake_text": frozenset({"warning"}),
    "ember_template_lint_json": frozenset({"error", "warning"}),
}


class ManifestValidationError(ValueError):
    """Raised when a manifest fails semantic validation."""


class DetectRules(BaseModel):
    model_config = ConfigDict(extra="forbid")

    files: list[str] = Field(min_length=1)
    lint_files: list[str] | None = None


class ProvenanceEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str
    sha256: str


class AnalyzerManifest(BaseModel):
    """One catalog analyzer definition (D1)."""

    model_config = ConfigDict(extra="forbid")

    id: str
    category: str
    languages: list[str]
    detect: DetectRules
    command: list[str]
    scope: str
    parser: str
    supports_fix: bool
    default_enabled: DefaultEnabled
    version: str
    runtime: RuntimeMode
    timeout_s: int = Field(gt=0)
    trust: TrustTier
    severity_map: dict[str, str]
    provenance: dict[str, ProvenanceEntry]
    network_allowlist: list[str]
    exclusive_group: str | None = None
    declared_unavailable: str | None = None

    @field_validator("severity_map")
    @classmethod
    def _severity_values_are_taxonomy_members(cls, value: dict[str, str]) -> dict[str, str]:
        invalid = {key: mapped for key, mapped in value.items() if mapped not in FINDING_SEVERITIES}
        if invalid:
            details = ", ".join(f"{key!r}->{mapped!r}" for key, mapped in invalid.items())
            msg = f"severity_map values must be review_taxonomy severities: {details}"
            raise ValueError(msg)
        return value


def _expand_braces(pattern: str) -> list[str]:
    match = _BRACE_RE.search(pattern)
    if match is None:
        return [pattern]
    prefix, options, suffix = (
        pattern[: match.start()],
        match.group(1).split(","),
        pattern[match.end() :],
    )
    expanded: list[str] = []
    for option in options:
        expanded.extend(_expand_braces(prefix + option + suffix))
    return expanded


def validate_manifest(
    manifest: AnalyzerManifest,
    *,
    strict_severity_map: bool | None = None,
    check_provenance: bool = True,
) -> None:
    """Validate semantic constraints beyond pydantic field checks."""
    if strict_severity_map is None:
        strict_severity_map = manifest.runtime == "repo-native"

    if check_provenance:
        for platform, entry in manifest.provenance.items():
            if not entry.sha256.strip():
                msg = f"provenance[{platform!r}] requires a non-empty sha256"
                raise ManifestValidationError(msg)

    if strict_severity_map:
        required = _PARSER_NATIVE_SEVERITIES.get(manifest.parser, frozenset())
        if required:
            mapped = set(manifest.severity_map)
            missing = sorted(required - mapped)
            if missing:
                msg = (
                    f"severity_map for parser {manifest.parser!r} must map native severities "
                    f"{sorted(required)!r}; unmapped: {missing!r}"
                )
                raise ManifestValidationError(msg)
            unknown = sorted(mapped - required)
            if unknown:
                msg = (
                    f"severity_map for parser {manifest.parser!r} contains unknown severities "
                    f"{unknown!r}; expected keys from {sorted(required)!r}"
                )
                raise ManifestValidationError(msg)


def load_manifest_yaml(raw: str, *, strict_severity_map: bool | None = None) -> AnalyzerManifest:
    """Parse and validate one manifest YAML document."""
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise ManifestValidationError(str(exc)) from exc
    if not isinstance(data, dict):
        msg = "manifest must be a mapping"
        raise ManifestValidationError(msg)
    try:
        manifest = AnalyzerManifest.model_validate(data)
    except ValueError as exc:
        raise ManifestValidationError(str(exc)) from exc
    validate_manifest(manifest, strict_severity_map=strict_severity_map, check_provenance=False)
    return manifest


def load_manifest_file(path: Path, *, strict_severity_map: bool | None = None) -> AnalyzerManifest:
    return load_manifest_yaml(
        path.read_text(encoding="utf-8"), strict_severity_map=strict_severity_map
    )


def dump_manifest_yaml(manifest: AnalyzerManifest) -> str:
    return yaml.safe_dump(manifest.model_dump(), sort_keys=False, allow_unicode=True)


def expand_detect_patterns(patterns: list[str]) -> list[str]:
    """Expand brace groups in detect file globs."""
    expanded: list[str] = []
    for pattern in patterns:
        expanded.extend(_expand_braces(pattern))
    return expanded


__all__ = [
    "AnalyzerManifest",
    "DefaultEnabled",
    "DetectRules",
    "ManifestValidationError",
    "ProvenanceEntry",
    "RuntimeMode",
    "TrustTier",
    "dump_manifest_yaml",
    "expand_detect_patterns",
    "load_manifest_file",
    "load_manifest_yaml",
    "validate_manifest",
]
