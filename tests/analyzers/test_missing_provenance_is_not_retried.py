"""A platform with no pinned build cannot be provisioned by trying again (#1519)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.analyzers.support import import_module


def test_missing_provenance_fails_once_without_a_retry_or_a_delay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    execution = import_module("mergecraft.analyzers.execution")
    provision = import_module("mergecraft.analyzers.provision")
    registry = import_module("mergecraft.analyzers.registry")
    resolve = import_module("mergecraft.analyzers.resolve")
    manifest = registry.get_manifest("checkmake").model_copy(update={"provenance": {}})
    plan = resolve.AnalyzerPlan(manifest_id=manifest.id, mode="managed", argv=("checkmake",))
    attempts: list[str] = []
    real = provision.provision_managed_binary

    def counted(**kwargs: object):
        attempts.append("attempt")
        return real(**kwargs)

    monkeypatch.setattr(provision, "provision_managed_binary", counted)
    monkeypatch.setattr(execution, "resolve_baked_binary", lambda _manifest: None)
    monkeypatch.setattr(
        execution.time, "sleep", lambda _s: pytest.fail("a missing pin must not wait to retry")
    )

    with pytest.raises(provision.MissingProvenanceError, match="no provenance for platform"):
        execution.provision_managed_argv(plan, manifest=manifest, repo_root=tmp_path)

    assert attempts == ["attempt"]


def test_missing_provenance_is_still_a_provision_error() -> None:
    provision = import_module("mergecraft.analyzers.provision")

    assert issubclass(provision.MissingProvenanceError, provision.ProvisionError)
