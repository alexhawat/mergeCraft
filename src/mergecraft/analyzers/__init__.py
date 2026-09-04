"""Analyzer platform — manifests, registry, resolution, and execution."""

from __future__ import annotations

from mergecraft.analyzers.finding import Finding, FindingValidationError, make_finding
from mergecraft.analyzers.manifest import (
    AnalyzerManifest,
    ManifestValidationError,
    dump_manifest_yaml,
    load_manifest_file,
    load_manifest_yaml,
    validate_manifest,
)
from mergecraft.analyzers.registry import detect_enabled, load_catalog
from mergecraft.analyzers.resolve import AnalyzerPlan, resolve_analyzer
from mergecraft.analyzers.run import AnalyzerOutcome, CheckStatus, run_plan, run_plans

__all__ = [
    "AnalyzerManifest",
    "AnalyzerOutcome",
    "AnalyzerPlan",
    "CheckStatus",
    "Finding",
    "FindingValidationError",
    "ManifestValidationError",
    "detect_enabled",
    "dump_manifest_yaml",
    "load_catalog",
    "load_manifest_file",
    "load_manifest_yaml",
    "make_finding",
    "resolve_analyzer",
    "run_plan",
    "run_plans",
    "validate_manifest",
]
