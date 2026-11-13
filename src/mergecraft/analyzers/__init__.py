"""Analyzer platform — manifests, registry, resolution, and execution."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
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

_EXPORT_MODULES = {
    "Finding": "mergecraft.analyzers.finding",
    "FindingValidationError": "mergecraft.analyzers.finding",
    "make_finding": "mergecraft.analyzers.finding",
    "AnalyzerManifest": "mergecraft.analyzers.manifest",
    "ManifestValidationError": "mergecraft.analyzers.manifest",
    "dump_manifest_yaml": "mergecraft.analyzers.manifest",
    "load_manifest_file": "mergecraft.analyzers.manifest",
    "load_manifest_yaml": "mergecraft.analyzers.manifest",
    "validate_manifest": "mergecraft.analyzers.manifest",
    "detect_enabled": "mergecraft.analyzers.registry",
    "load_catalog": "mergecraft.analyzers.registry",
    "AnalyzerPlan": "mergecraft.analyzers.resolve",
    "resolve_analyzer": "mergecraft.analyzers.resolve",
    "AnalyzerOutcome": "mergecraft.analyzers.run",
    "CheckStatus": "mergecraft.analyzers.run",
    "run_plan": "mergecraft.analyzers.run",
    "run_plans": "mergecraft.analyzers.run",
}

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


def __getattr__(name: str) -> Any:
    """Resolve public re-exports without loading unrelated runtime subsystems."""
    if name not in _EXPORT_MODULES:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(_EXPORT_MODULES[name]), name)
    globals()[name] = value
    return value
